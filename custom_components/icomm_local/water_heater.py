from homeassistant.components.water_heater import WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from .entity import LocalEntity

MODE_TO_HA = {'hybrid':'eco','heat_pump':'heat_pump','electric':'electric','vacation':'vacation'}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([LocalWaterHeater(entry)])


class LocalWaterHeater(LocalEntity, WaterHeaterEntity):
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = 95
    _attr_target_temperature_step = 1
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE
    _attr_operation_list = list(MODE_TO_HA.values())

    def __init__(self, entry):
        super().__init__(entry, None, 'water_heater')
        self._attr_max_temp = entry.data['maximum']

    @property
    def target_temperature(self):
        return self.heater.state.target_f if self.heater.state else None

    @property
    def current_operation(self):
        return MODE_TO_HA.get(self.heater.state.mode) if self.heater.state else None

    @property
    def extra_state_attributes(self):
        return {'duration_days': self.heater.state.duration_days if self.heater.state else None,
                'connection': 'local', 'protocol': 'emulated_cloud' if self.entry.data.get('connection')=='emulator' else 'lan', 'last_local_update': self.heater.last_update,
                'last_error': self.heater.last_error}

    async def async_set_temperature(self, **kwargs):
        try:
            await self.heater.set_target(kwargs[ATTR_TEMPERATURE])
        except (ValueError, ConnectionError, TimeoutError) as error:
            raise HomeAssistantError(str(error)) from error

    async def async_set_operation_mode(self, operation_mode):
        mode = next((key for key,value in MODE_TO_HA.items() if value == operation_mode), None)
        if mode is None:
            raise HomeAssistantError('Unsupported operating mode')
        try:
            await self.heater.set_mode(mode)
        except (ValueError, ConnectionError, TimeoutError) as error:
            raise HomeAssistantError(str(error)) from error
