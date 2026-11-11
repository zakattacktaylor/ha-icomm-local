"""Local iCOMM water heater integration. No cloud login during operation."""
DOMAIN = 'icomm_local'
PLATFORMS = ['water_heater', 'sensor']


async def async_setup_entry(hass, entry):
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from .lan import LocalHeater
    data = entry.data
    on_update=lambda: async_dispatcher_send(hass, f'{DOMAIN}_{entry.entry_id}')
    if data.get('connection')=='emulator':
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        from .emulator_client import EmulatorHeater
        heater=EmulatorHeater(async_get_clientsession(hass),data['host'],data['api_token'],on_update,data.get('port',8787))
    else:
        heater = LocalHeater(data['host'], data['callback_host'], data['lan_key'],
            data['key_id'], data['port'], data['maximum'],on_update=on_update)
    await heater.start()
    entry.runtime_data = heater
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await heater.stop()
        raise
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.stop()
        return True
    return False
