"""Configure a previously provisioned iCOMM LAN key."""
import ipaddress
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv, selector
from . import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id='user',menu_options=['emulator','lan'])

    async def async_step_emulator(self,user_input=None):
        errors={}
        if user_input:
            try:
                address=ipaddress.IPv4Address(user_input['host'])
                if not address.is_private or address.is_loopback or address.is_unspecified:raise ValueError()
                if len(user_input['api_token'])<24:raise ValueError()
            except (ValueError,KeyError):errors['base']='invalid_config'
            else:
                await self.async_set_unique_id('emulator_'+user_input['host'])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title='Water heater (local emulator)',data=dict(user_input,connection='emulator',maximum=130))
        return self.async_show_form(step_id='emulator',data_schema=vol.Schema({
            vol.Required('host'):str,
            vol.Required('api_token'):selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Required('port',default=8787):cv.port}),errors=errors)

    async def async_step_lan(self, user_input=None):
        errors = {}
        if user_input:
            try:
                for field in ('host', 'callback_host'):
                    address = ipaddress.IPv4Address(user_input[field])
                    if not address.is_private or address.is_loopback or address.is_unspecified:
                        raise ValueError('Use a private LAN IPv4 address')
                if not 16 <= len(user_input['lan_key']) <= 32 or not user_input['lan_key'].isascii():
                    raise ValueError('Invalid key')
            except (ValueError, KeyError):
                errors['base'] = 'invalid_config'
            else:
                await self.async_set_unique_id(user_input['host'])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title='Water heater', data=user_input)
        schema = vol.Schema({
            vol.Required('host'): str,
            vol.Required('callback_host'): str,
            vol.Required('lan_key'): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Required('key_id', default=1): vol.All(vol.Coerce(int), vol.Range(min=1,max=65535)),
            vol.Required('port', default=8888): cv.port,
            vol.Required('maximum', default=130): vol.All(vol.Coerce(int),vol.Range(min=95,max=130)),
        })
        return self.async_show_form(step_id='lan', data_schema=schema, errors=errors)
