import logging

from flatland import Boolean, Form
from microdrop.app_context import get_app
from microdrop.plugin_helpers import StepOptionsController
from microdrop.plugin_manager import (IPlugin, Plugin, implements,
                                      PluginGlobals)
import conda_helpers as ch
import mr_box_peripheral_board as mb
import path_helpers as ph

logger = logging.getLogger(__name__)

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

# Add plugin to `"microdrop.managed"` plugin namespace.
PluginGlobals.push_env('microdrop.managed')


class MrBoxPeripheralBoardPlugin(Plugin, StepOptionsController):
    '''
    This class is automatically registered with the PluginManager.
    '''
    implements(IPlugin)

    plugin_name = ph.path(__file__).realpath().parent.name
    try:
        version = ch.package_version(plugin_name).get('version')
    except NameError:
        version = 'v0.0.0+unknown'

    StepFields = Form.of(Boolean.named('magnet_engaged')
                         .using(default=False, optional=True))

    def __init__(self):
        super(MrBoxPeripheralBoardPlugin, self).__init__()
        self.board = None
        # XXX `name` attribute is required in addition to `plugin_name`
        #
        # The `name` attribute is required in addition to the `plugin_name`
        # attribute because MicroDrop uses it for plugin labels in, for
        # example, the plugin manager dialog.
        self.name = self.plugin_name

    def reset_board_state(self):
        '''
        Reset MR-Box peripheral board to default state.
        '''
        if self.board is None:
            return

        # TODO Add reset method for each component (e.g., z-stage, pump, PMT)
        # TODO to respective `mr-box-peripheral-board.py` C++ classes code.

        # Home the magnet z-stage.
        self.board.zstage_home()

        if not self.board.zstage_at_home():
            logger.warning('Unable to verify z-stage is in homed position.')

        # TODO Reset remainder board state
        # Deactivate the pump.
        # Set pump frequency to zero.
        # Close the PMT shutter.
        # Set PMT control voltage to zero.

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
                board_config = self.board.config
                if step_options.get('magnet_engaged'):
                    # Choose magnet "up" position.
                    position = board_config.zstage_up_position
                else:
                    # Choose magnet "down" position.
                    position = board_config.zstage_down_position
                # Send board request to move magnet to position.
                self.board.zstage.move_to(position)
            except Exception:
                logger.error('[%s] Error applying step options.', __name__,
                             exc_info=True)

    def open_board_connection(self):
        '''
        Establish serial connection to MR-Box peripheral board.
        '''
        try:
            if self.board is not None:
                # Close existing board connection.
                self.board.close()

            # Try to connect to peripheral board through serial connection.
            self.board = mb.SerialProxy()

            # Serial connection to peripheral **successfully established**.
            logger.info('Serial connection to peripheral board **successfully'
                        ' established** on port `%s`', self.board.port)
            logger.info('Peripheral board properties:\n%s',
                        self.board.properties)

            logger.info('Reset board state to defaults.')
            self.reset_board_state()
        except Exception:
            # Serial connection to peripheral **could not be established**.
            logger.warning('Serial connection to peripheral board **could not'
                           ' be established**.', exc_info=True)

    def close_board_connection(self):
        '''
        Close serial connection to MR-Box peripheral board.
        '''
        if self.board is not None:
            # Close board connection and release serial connection.
            self.board.close()

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
        try:
            super(MrBoxPeripheralBoardPlugin, self).on_plugin_enable()
        except AttributeError:
            pass
        self.open_board_connection()

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

    def on_protocol_run(self):
        '''
        Handler called when a protocol starts running.
        '''
        # Reset board state before executing protocol.  State will be updated
        # during the execution of each step based on the selected step options.
        self.reset_board_state()

    def on_protocol_pause(self):
        '''
        Handler called when a protocol is paused.
        '''
        # Reset board state when stopping a protocol.
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
        if app.running or app.realtime_mode:
            # Apply step options.
            options = self.get_step_options()
            self.apply_step_options(options)


PluginGlobals.pop_env()
