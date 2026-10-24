"""Carbon MMO Foundation - engine-side Python packages.

Layering (each layer only imports the ones above it):

    cmmo.mathbridge   MODULE: math   Carbon Vector3 (C++), pure-Python fallback
    cmmo.net          MODULE: net    transport / connections / serialization / heartbeat / sync
    cmmo.ecs          MODULE: ecs    entities + components + systems, no engine types inside
    cmmo.nav          MODULE: nav    pathfinding adapters (Destiny, kinematic fallback)

Game rules live outside this package (see cmmo_game/). Nothing in cmmo imports them.
"""

__version__ = "0.1.0"
