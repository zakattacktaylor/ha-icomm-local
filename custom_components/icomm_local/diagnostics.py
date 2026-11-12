"""Diagnostics deliberately omit keys, addresses, identifiers, and raw properties."""
from dataclasses import asdict
import time


async def async_get_config_entry_diagnostics(hass, entry):
    heater = entry.runtime_data
    return {'available': heater.available,
        'seconds_since_local_telemetry': round(time.time()-heater.last_update) if heater.last_update else None,
        'state': asdict(heater.state) if heater.state else None,
        'queued_requests': len(getattr(heater,'queue',[])),
        'events': [e for e in getattr(heater,'events',[]) if e['kind'] != 'registration_failed']}
