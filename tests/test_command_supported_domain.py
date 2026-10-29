import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from domain import command_supported
def test_hall_light_supports_on():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'ON') is True

def test_hall_light_does_not_support_lock():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'LOCK') is False

def test_hall_light_supports_off_middle_of_list():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'OFF') is True

def test_hall_light_supports_dim_end_of_list():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'DIM') is True

def test_hall_light_supports_lowercase_dim():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'dim') is True

def test_hall_light_does_not_support_partial_command():
    assert command_supported({'capabilities':'ON,OFF,DIM'},'DI') is False

def test_capabilities_with_spaces_supports_off():
    assert command_supported({'capabilities':'ON ,OFF ,DIM '},'OFF') is True

def test_device_with_no_capabilities_does_not_support_on():
    assert command_supported({'capabilities':None},'ON') is False

def test_device_with_empty_capabilities_does_not_support_on():
    assert command_supported({'capabilities':''},'ON') is False

def test_device_with_no_capabilities_does_not_support_empty_command():
    assert command_supported({'capabilities':None},'') is False

def test_hall_light_does_not_support_missing_command():
    assert command_supported({'capabilities':'ON,OFF,DIM'},None) is False

def test_lock_battery_is_not_a_command():
    assert command_supported({'capabilities':'LOCK,UNLOCK,BATTERY'},'BATTERY') is False