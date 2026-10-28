import os, sys, sqlite3
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from domain import compare, is_cooldown, command_supported, can_access_home

def test_battery_just_below_limit_matches():
    assert compare('<',19,'20') is True

def test_battery_exactly_at_limit_does_not_match():
    assert compare('<',20,'20') is False

def test_battery_just_above_limit_does_not_match():
    assert compare('<',21,'20') is False

def test_motion_detected_matches_motion_rule():
    assert compare('==',1,'1') is True

def test_no_motion_does_not_match_motion_rule():
    assert compare('==',0,'1') is False

def test_equal_numbers_written_differently_match():
    assert compare('==','1.0','1') is True

def test_notequal_with_different_values():
    assert compare('!=',19,'20') is True

def test_unsupported_operator_returns_false():
    assert compare('=!',19,'20') is False

def test_greater_that_above_limit_returns_true():
    assert compare('>',21,'20') is True

def test_greater_that_below_limit_returns_false():
    assert compare('>',19,'20') is False

def test_greater_than_exactly_at_limit_returns_false():
    assert compare('>',20,'20') is False

def test_greater_than_or_equal_exactly_at_limit_returns_true():
    assert compare('>=',20,'20') is True

def test_greater_than_or_equal_below_limit_returns_false():
    assert compare('>=',19,'20') is False

def test_less_than_or_equal_exactly_at_limit_returns_true():
    assert compare('<=',20,'20') is True

def test_less_than_or_equal_directly_above_the_limit_returns_false():
    assert compare('<=',21,'20') is False

def test_text_same_state_matches():
    assert compare('==','UNLOCKED','UNLOCKED') is True

def test_text_different_state_does_not_match():
    assert compare('==','LOCKED','UNLOCKED') is False

def test_text_different_case_matches():
    assert compare('==','unlocked','UNLOCKED') is True

def test_text_trailing_space_matches():
    assert compare('==','UNLOCKED ','UNLOCKED')is True

def test_text_not_equal_different_states_returns_true():
    assert compare('!=','LOCKED','UNLOCKED')is True

def test_text_not_equal_same_state_returns_false():
    assert compare('!=','LOCKED','LOCKED')is False

def test_missing_value_does_not_match_text_none():
    assert compare('==',None,'None')is False

def test_missing_value_does_not_match_battery_rule():
    assert compare('<',None,'20')is False

def test_empty_value_does_not_match_text_rule():
    assert compare('==','','UNLOCKED')is False

def test_empty_value_does_not_match_battery_rule():
    assert compare('<','','20')is False

def test_text_greater_than_number_returns_false():
    assert compare('>','OPEN','5')is False

def test_text_less_than_number_returns_false():
    assert compare('<','OPEN','5')is False

