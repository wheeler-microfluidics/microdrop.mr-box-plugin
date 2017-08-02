import logging

from flatland import Boolean, Integer, Float, Form
from flatland.validation import ValueAtLeast
from microdrop.app_context import get_app
from microdrop.plugin_helpers import StepOptionsController
from microdrop.plugin_manager import (IPlugin, Plugin, implements,
                                      PluginGlobals)
import conda_helpers as ch
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

    StepFields = Form.of(Boolean.named('bool_field')
                         .using(default=False, optional=True),
                         Float.named('float_field')
                         .using(default=0, optional=True,
                                validators=[ValueAtLeast(minimum=0)]))

    def __init__(self):
        super(MrBoxPeripheralBoardPlugin, self).__init__()

    def on_plugin_enable(self):
        super(MrBoxPeripheralBoardPlugin, self).on_plugin_enable()

    def on_plugin_disable(self):
        try:
            super(MrBoxPeripheralBoardPlugin, self).on_plugin_disable()
        except AttributeError:
            pass

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
        # ... Perform step actions ...

    def on_protocol_run(self):
        '''
        Handler called when a protocol starts running.
        '''
        pass

    def on_protocol_pause(self):
        '''
        Handler called when a protocol is paused.
        '''
        app = get_app()
        self._kill_running_step()
        if self.control_board and not app.realtime_mode:
            # Turn off all electrodes
            logger.debug('Turning off all electrodes.')
            self.control_board.hv_output_enabled = False


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
        pass

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
        pass


PluginGlobals.pop_env()
