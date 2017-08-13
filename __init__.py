import datetime as dt
import logging
import time
import serial

from flatland import Boolean, Float, Form, Integer
from flatland.validation import ValueAtLeast, ValueAtMost
from microdrop.app_context import get_app
from microdrop.plugin_helpers import AppDataController, StepOptionsController
from pygtkhelpers.ui.objectlist import PropertyMapper
from pygtkhelpers.utils import dict_to_form
from pygtkhelpers.ui.extra_dialogs import yesno, FormViewDialog

from microdrop.plugin_manager import (IPlugin, Plugin, implements, emit_signal,
                                      get_service_instance_by_name,
                                      PluginGlobals)
import gobject
import gtk
import path_helpers as ph
import microdrop_utility as utility

from mr_box_peripheral_board.max11210_adc_ui import (MAX11210_begin,
                                                     MAX11210_status)
import mr_box_peripheral_board as mrbox
import mr_box_peripheral_board.ui.gtk.measure_dialog
from mr_box_peripheral_board.ui.gtk.pump_ui import PumpControl


logger = logging.getLogger(__name__)

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

# Add plugin to `"microdrop.managed"` plugin namespace.
PluginGlobals.push_env('microdrop.managed')


class MrBoxPeripheralBoardPlugin(AppDataController, StepOptionsController,
                                 Plugin):
    '''
    This class is automatically registered with the PluginManager.
    '''
    implements(IPlugin)

    plugin_name = str(ph.path(__file__).realpath().parent.name)
    try:
        version = __version__
    except NameError:
        version = 'v0.0.0+unknown'

    AppFields = Form.of(Boolean.named('Use PMT y-axis SI units')
                        .using(default=True, optional=True))

    StepFields = Form.of(Boolean.named('Magnet')
                         .using(default=False, optional=True),
                         #PMT Fields
                         Boolean.named('Measure_PMT')
                         .using(default=False, optional=True),
                         # Only allow PMT Duration to be set if `Measure_PMT` field
                         # is set to `True`.
                         Integer.named('Measurement_duration_(s)')
                         .using(default=10, optional=True,
                                validators= [ValueAtLeast(minimum=1)],
                                properties={'mappers':
                                            [PropertyMapper('sensitive',
                                                            attr='Measure_PMT'),
                                             PropertyMapper('editable',
                                                            attr='Measure_PMT')]}),
                         # Only allow ADC Gain to be set if `Measure_PMT` field
                         # is set to `True`.
                         #TODO Convert ADC Gain to dropdown list  with valid_values = (1,2,4,8,16)
                         Integer.named('ADC_Gain')
                         .using(default=1, optional=True,
                                validators= [ValueAtLeast(minimum=1), ValueAtMost(maximum=16)],
                                properties={'mappers':
                                            [PropertyMapper('sensitive',
                                                            attr='Measure_PMT'),
                                             PropertyMapper('editable',
                                                            attr='Measure_PMT')]}),
                         #Pump Fields
                         Boolean.named('Pump').using(default=False,
                                                     optional=True),
                         # Only allow pump frequency to be set if `Pump` field
                         # is set to `True`.
                         Float.named('Pump_frequency_(hz)')
                         .using(default=1000, optional=True,
                                validators=[ValueAtLeast(minimum=1)],
                                properties={'mappers':
                                            [PropertyMapper('sensitive',
                                                            attr='Pump'),
                                             PropertyMapper('editable',
                                                            attr='Pump')]}),
                         # Only allow pump duration to be set if `Pump` field
                         # is set to `True`.
                         Float.named('Pump_duration_(s)')
                         .using(default=.1, optional=True,
                                validators=[ValueAtLeast(minimum=.1)],
                                properties={'mappers':
                                            [PropertyMapper('sensitive',
                                                            attr='Pump'),
                                             PropertyMapper('editable',
                                                            attr='Pump')]}))

    def __init__(self):
        super(MrBoxPeripheralBoardPlugin, self).__init__()
        self.board = None
        # XXX `name` attribute is required in addition to `plugin_name`
        #
        # The `name` attribute is required in addition to the `plugin_name`
        # attribute because MicroDrop uses it for plugin labels in, for
        # example, the plugin manager dialog.
        self.name = self.plugin_name

        # Flag to indicate whether user has already been warned about the board
        # not being connected when trying to set board state.
        self._user_warned = False

        # `dropbot.SerialProxy` instance
        self.dropbot_remote = None

        # Latch to, e.g., config menus, only once
        self.initialized = False

    def reset_board_state(self):
        '''
        Reset MR-Box peripheral board to default state.
        '''
        # Reset user warned state (i.e., warn user next time board settings
        # are applied when board is not connected).
        self._user_warned = False

        if self.board is None:
            return

        # TODO Add reset method for each component (e.g., z-stage, pump, PMT)
        # TODO to respective `mr-box-peripheral-board.py` C++ classes code.

        # Home the magnet z-stage.
        self.board.zstage.home()

        if not self.board.zstage.is_down:
            logger.warning('Unable to verify z-stage is in homed position.')

        # Deactivate the pump.
        self.board.pump_deactivate()
        # Set pump frequency to zero.
        self.board.pump_frequency_set(0)
        # Close the PMT shutter.
        self.board.pmt_close_shutter()
        # Set PMT control voltage to zero.
        self.board.pmt_set_pot(0)
        #Start the ADC and Perform ADC Calibration
        MAX11210_begin(self.board)
        MAX11210_status(self.board)

    def apply_step_options(self, step_options):
        '''
        Apply the specified step options.

        Parameters
        ----------
        step_options : dict
            Dictionary containing the MR-Box peripheral board plugin options
            for a protocol step.
        '''
        if self.board is not None:
            # Apply board hardware options.
            try:
                # Magnet z-stage
                # --------------
                if step_options.get('Magnet'):
                    # Send board request to move magnet to position (if it is
                    # already engaged, this function does nothing).
                    self.board.zstage.up()
                else:
                    # Send board request to move magnet to down position (if
                    # it is already engaged, this function does nothing).
                    self.board.zstage.down()

                # Pump
                # ----
                if step_options.get('Pump'):
                    # Launch pump control dialog.
                    frequency_hz = step_options.get('Pump_frequency_(hz)')
                    duration_s = step_options.get('Pump_duration_(s)')
                    self.pump_control_dialog(frequency_hz, duration_s)

                # PMT/ADC
                # -------
                if step_options.get('Measure_PMT'):
                    #Start the ADC and Perform ADC Calibration
                    MAX11210_begin(self.board)
                    ''' Set PMT control voltage via digipot.'''
                    #Divide the control voltage by the maximum 1100 mV and convert it to digipot steps
                    pmt_digipot = int((self.board.config.pmt_control_voltage/1100.)*255)
                    self.board.pmt_set_pot(pmt_digipot)
                    # Launch PMT measure dialog.
                    delta_t = dt.timedelta(seconds=1)
                    #Set the digital gain of ADC
                    adc_dgain = step_options.get('ADC_Gain')
                    # Construct a function compatible with `measure_dialog` to
                    # read from MAX11210 ADC.
                    data_func = (mrbox.ui.gtk.measure_dialog
                                 .adc_data_func_factory(proxy=self.board,
                                                        delta_t=delta_t,
                                                        adc_dgain=adc_dgain))

                    # Use constructed function to launch measurement dialog for
                    # the duration specified by the step options.
                    duration_s = step_options.get('Measurement_duration_(s)')+1
                    app_values = self.get_app_values()
                    use_si_prefixes = app_values.get('Use PMT y-axis SI prefixes')
                    data = (mrbox.ui.gtk.measure_dialog
                            .measure_dialog(data_func, duration_s=duration_s,
                                            auto_start=True, auto_close=False,
                                            si_units=use_si_prefixes))
                    if data is not None:
                        # Append measured data as JSON line to [new-line
                        # delimited JSON][1] file for step.
                        #
                        # Each line of results can be loaded using
                        # `pandas.read_json(...)`.
                        #
                        # [1]: http://ndjson.org/
                        app = get_app()
                        filename = ('PMT_readings-step%04d.ndjson' %
                                    app.protocol.current_step_number)
                        log_dir = app.experiment_log.get_log_path()
                        log_dir.makedirs_p()
                        with log_dir.joinpath(filename).open('a') as output:
                            data.to_json(output)
                            output.write('\n')
            except Exception:
                logger.error('[%s] Error applying step options.', __name__,
                             exc_info=True)
        elif not self._user_warned:
            logger.warning('[%s] Cannot apply board settings since board is '
                           'not connected.', __name__, exc_info=True)
            # Do not warn user again until after the next connection attempt.
            self._user_warned = True

    def pump_control_dialog(self, frequency_hz, duration_s):
        # `PumpControl` class uses threads.  Need to initialize GTK to use threads.
        # See [here][1] for more information.
        #
        # [1]: http://faq.pygtk.org/index.py?req=show&file=faq20.001.htp
        gtk.gdk.threads_init()

        # Create pump control view widget.
        pump_control_view = PumpControl(self.board, frequency_hz=frequency_hz,
                                        duration_s=duration_s)

        # Start pump automatically.
        gobject.idle_add(pump_control_view.start)

        # Create dialog window to wrap pump control view widget.
        dialog = gtk.Dialog()
        dialog.get_content_area().pack_start(pump_control_view.widget, True, True)
        dialog.set_position(gtk.WIN_POS_MOUSE)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def open_board_connection(self):
        '''
        Establish serial connection to MR-Box peripheral board.
        '''
        # Try to connect to peripheral board through serial connection.

        # XXX Try to connect multiple times.
        # See [issue 1][1] on the [MR-Box peripheral board firmware
        # project][2].
        #
        # [1]: https://github.com/wheeler-microfluidics/mr-box-peripheral-board.py/issues/1
        # [2]: https://github.com/wheeler-microfluidics/mr-box-peripheral-board.py
        retry_count = 2
        for i in xrange(retry_count):
            try:
                self.board.close()
                self.board = None
            except Exception:
                pass

            try:
                self.board = mrbox.SerialProxy()

                host_software_version = utility.Version.fromstring(
                    str(self.board.host_software_version))
                remote_software_version = utility.Version.fromstring(
                    str(self.board.remote_software_version))

                # Offer to reflash the firmware if the major and minor versions
                # are not not identical. If micro versions are different,
                # the firmware is assumed to be compatible. See [1]
                #
                # [1]: https://github.com/wheeler-microfluidics/base-node-rpc/
                #              issues/8
                if (host_software_version.major != remote_software_version.major or
                    host_software_version.minor != remote_software_version.minor):
                    response = yesno("The MR-box peripheral board firmware "
                                     "version (%s) does not match the driver "
                                     "version (%s). Update firmware?" %
                                     (remote_software_version,
                                      host_software_version))
                    if response == gtk.RESPONSE_YES:
                        self.on_flash_firmware()

                # Serial connection to peripheral **successfully established**.
                logger.info('Serial connection to peripheral board **successfully'
                            ' established** on port `%s`', self.board.port)
                logger.info('Peripheral board properties:\n%s',
                            self.board.properties)
                logger.info('Reset board state to defaults.')
                break
            except (serial.SerialException, IOError):
                time.sleep(1)
        else:
            # Serial connection to peripheral **could not be established**.
            logger.warning('Serial connection to peripheral board could not '
                           'be established.')

    def on_edit_configuration(self, widget=None, data=None):
        '''
        Display a dialog to manually edit the configuration settings.
        '''
        config = self.board.config
        form = dict_to_form(config)
        dialog = FormViewDialog(form, 'Edit configuration settings')
        valid, response = dialog.run()
        if valid:
            self.board.update_config(**response)

    def on_flash_firmware(self, widget=None, data=None):
        app = get_app()
        try:
            self.board.flash_firmware()
            app.main_window_controller.info("Firmware updated successfully.",
                                            "Firmware update")
        except Exception, why:
            logger.error("Problem flashing firmware. ""%s" % why)

    def close_board_connection(self):
        '''
        Close serial connection to MR-Box peripheral board.
        '''
        if self.board is not None:
            # Close board connection and release serial connection.
            self.board.close()

    def get_schedule_requests(self, function_name):
        """
        Returns a list of scheduling requests (i.e., ScheduleRequest
        instances) for the function specified by function_name.
        """
        # TODO: this should be re-enabled once we can get the
        # mr-box-peripheral-board to connect **after** the Dropbot.
        #if function_name in ['on_plugin_enable']:
        #    return [ScheduleRequest('dropbot_plugin', self.name)]
        return []

    ###########################################################################
    # MicroDrop pyutillib plugin signal handlers
    # ------------------------------------------
    ###########################################################################
    def on_plugin_enable(self):
        '''
        Handler called when plugin is enabled.

        For example, when the MicroDrop application is **launched**, or when
        the plugin is **enabled** from the plugin manager dialog.
        '''
        self.open_board_connection()
        self.reset_board_state()
        if not self.initialized:
            app = get_app()
            self.tools_menu_item = gtk.MenuItem("MR-Box")
            app.main_window_controller.menu_tools.append(self.tools_menu_item)
            self.tools_menu = gtk.Menu()
            self.tools_menu_item.set_submenu(self.tools_menu)

            self.edit_config_menu_item = \
                gtk.MenuItem("Edit configuration settings...")
            self.tools_menu.append(self.edit_config_menu_item)
            self.edit_config_menu_item.connect("activate",
                                               self.on_edit_configuration)
            self.edit_config_menu_item.show()
            self.initialized = True

        # if we're connected to the board, display the menu
        if self.board:
            self.tools_menu.show()
            self.tools_menu_item.show()

        try:
            super(MrBoxPeripheralBoardPlugin, self).on_plugin_enable()
        except AttributeError:
            pass

    def initialize_connection_with_dropbot(self):
        '''
        If the dropbot plugin is installed and enabled, try getting its
        reference.
        '''
        try:
            service = get_service_instance_by_name('dropbot_plugin')
            if service.enabled():
                self.dropbot_remote = service.control_board
            assert(self.dropbot_remote.properties.package_name == 'dropbot')
        except Exception:
            logger.debug('[%s] Could not communicate with Dropbot.', __name__,
                         exc_info=True)
            logger.warning('Could not communicate with DropBot.')

        try:
            if self.dropbot_remote:
                env = self.dropbot_remote.get_environment_state()
                logger.info('temp=%.1fC, Rel. humidity=%.1f%%' %
                            (env['temperature_celsius'],
                             100 * env['relative_humidity']))
        except Exception:
            logger.warning('Could not get temperature/humidity data.')

    def on_plugin_disable(self):
        '''
        Handler called when plugin is disabled.

        For example, when the MicroDrop application is **closed**, or when the
        plugin is **disabled** from the plugin manager dialog.
        '''
        try:
            super(MrBoxPeripheralBoardPlugin, self).on_plugin_disable()
        except AttributeError:
            pass
        self.close_board_connection()
        self.tools_menu.hide()
        self.tools_menu_item.hide()

    def on_protocol_run(self):
        '''
        Handler called when a protocol starts running.
        '''
        # TODO: this should be run in on_plugin_enable; however, the
        # mr-box-peripheral-board seems to have trouble connecting **after**
        # the DropBot has connected.
        self.initialize_connection_with_dropbot()

    def on_protocol_pause(self):
        '''
        Handler called when a protocol is paused.
        '''
        # Close the PMT shutter.
        self.board.pmt_close_shutter()

    def on_experiment_log_changed(self, experiment_log):
        '''
        Handler called when a new experiment starts.
        '''
        logger.info('Reset board state to defaults.')
        self.reset_board_state()

    def on_step_options_changed(self, plugin, step_number):
        '''
        Handler called when field values for the specified plugin and step.

        Parameters
        ----------
        plugin : str
            Name of plugin.
        step_number : int
            Step index number.
        '''
        # Step options have changed.
        app = get_app()

        if all([plugin == self.plugin_name, app.running or app.realtime_mode,
                step_number == app.protocol.current_step_number]):
            # Apply step options.
            options = self.get_step_options()
            self.apply_step_options(options)

    def on_step_run(self):
        '''
        Handler called whenever a step is executed.

        Plugins that handle this signal **MUST** emit the ``on_step_complete``
        signal once they have completed the step.  The protocol controller will
        wait until all plugins have completed the current step before
        proceeding.
        '''
        # Get latest step field values for this plugin.
        options = self.get_step_options()
        # Apply step options
        self.apply_step_options(options)

        # log environmental data
        try:
            app = get_app()
            env = self.dropbot_remote.get_environment_state()
            app.experiment_log.add_data({"environment": env}, self.name)
            logger.info('temp=%.1fC, Rel. humidity=%.1f%%' %
                        (env['temperature_celsius'],
                         100 * env['relative_humidity']))

        except Exception:
            logger.debug('[%s] Failed to get environment data.', __name__,
                          exc_info=True)

        emit_signal('on_step_complete', [self.name])

    def on_step_swapped(self, original_step_number, new_step_number):
        '''
        Handler called when a new step is activated/selected.

        Parameters
        ----------
        original_step_number : int
            Step number of previously activated step.
        new_step_number : int
            Step number of newly activated step.
        '''
        # Step options have changed.
        app = get_app()
        if app.realtime_mode:
            # Apply step options.
            options = self.get_step_options()
            self.apply_step_options(options)


PluginGlobals.pop_env()
