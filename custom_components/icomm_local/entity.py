from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from . import DOMAIN


class LocalEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, name, suffix):
        self.entry = entry
        self.heater = entry.runtime_data
        self._attr_name = name
        self._attr_unique_id = f'{entry.unique_id}_{suffix}'
        self._attr_device_info = {'identifiers': {(DOMAIN, entry.unique_id)},
            'manufacturer': 'A. O. Smith', 'name': 'Water heater',
            'model': 'iCOMM NextGen heat pump',
            'configuration_url': f'http://{entry.data["host"]}'}

    @property
    def available(self):
        return self.heater.available

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass,
            f'{DOMAIN}_{self.entry.entry_id}', self.async_write_ha_state))
