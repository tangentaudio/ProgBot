# ProgHead

Programmer head controller, based on an Arduino Nano clone.  Communicates over serial (USB-Serial) to host and allows control of power and logic sequencing relays, as well as provides status about board contact.

## Commands

- `Stat` - Request contact status
- `PowerOn` or `PowerOff` - Control the power relay.  Response `OK PowerOn` or `OK PowerOff`
- `LogicOn` or `LogicOff` - Control the logic relays (SWD pins, UART pins).  Response `OK LogicOn` or `OK LogicOff`
- `AllOn` or `AllOff` - Control both sets of relays simultaneously.  Response `OK AllOn` or `OK AllOff`

## Error Response

Any unrecognized command returns `ERROR`

