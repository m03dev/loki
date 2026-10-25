// MODULE: world.gameplay
// Components: small pieces of behaviour you add to any actor in the Inspector (like Unreal's Add Component).
// A component is JSON in the level ({"type": "Rotator", "speed": [0, 45, 0]}) and, in Play, a C++ Behaviour.
//
//   Physics   Box Collider, Sphere Collider          (solid, or "trigger": reports instead of blocking)
//   Motion    Rotator, Bobber, Mover                 (spin, float up and down, slide back and forth)
//   Gameplay  Trigger Event, Pickup                  (on enter: message / heal / damage / XP / teleport / toggle;
//                                                     touch to collect XP or health, optionally respawning)
//
// Add a component type: write a Behaviour subclass and one line in RegisterBuiltins() (Gameplay.cpp) - the
// Inspector, saving and Play pick it up from the registry. Colliders are read by the physics module.
#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "world/World.h"

namespace cmmo::world
{
class Behaviour
{
public:
	virtual ~Behaviour() = default;
	virtual void Start( PlaySession& ) {}
	virtual void Tick( PlaySession&, float /*time*/, float /*dt*/ ) {}
	virtual void Enter( PlaySession& ) {}   // the player stepped into this actor's trigger
	virtual void Exit( PlaySession& ) {}
	uint32_t actor = 0;
	json config;
};

struct ComponentInfo
{
	std::string type, label, what, group;
	std::string icon;                                                   // an icon key ("box", "rotate"...); the editor maps it
	json defaults;
	std::function<std::unique_ptr<Behaviour>()> make;                   // empty: data only (colliders)
};

const std::vector<ComponentInfo>& ComponentTypes();
const ComponentInfo* FindComponentType( const std::string& type );
json MakeComponent( const std::string& type );   // the defaults + "type"
}
