from domain import compare,command_supported

def test_numeric_compare(): assert compare('<',10,20)
def test_equality(): assert compare('==','ON','ON')
def test_capability(): assert command_supported({'capabilities':'ON,OFF,DIM'},'DIM')
