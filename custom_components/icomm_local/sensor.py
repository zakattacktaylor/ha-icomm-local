from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature
from .entity import LocalEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TankTemperature(entry, position) for position in ('top','middle','bottom')])


class TankTemperature(LocalEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry, position):
        super().__init__(entry, f'Tank {position} temperature (experimental)', position)
        self.position = position

    @property
    def native_value(self):
        return getattr(self.heater.state, f'{self.position}_f') if self.heater.state else None
