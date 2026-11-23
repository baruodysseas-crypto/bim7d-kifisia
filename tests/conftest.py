import os

# The thesis edition is closed to new projects; the tests need to create temporary ones.
os.environ["BIM7D_ALLOW_NEW"] = "1"
# The tests never go to the network: live sources are fed from recorded responses (tests/fixtures).
os.environ["BIM7D_OFFLINE"] = "1"
