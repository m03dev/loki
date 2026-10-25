// MODULE: world.physics
// Collision for Play: every actor with a collider becomes an axis-aligned box (rotated actors use the box that
// encloses them). Solid boxes block the player and creatures and can be stood on; trigger boxes report who is inside.
//
//   colliders  Shape actors (unless "collision" is off), Box / Sphere Collider components, Trigger Box actors
//   player     a vertical capsule (radius, height); steps up ledges lower than kStepHeight
//
// Rebuilt every Play tick from the world's transforms, so moving and rotating actors collide where they are now.
// Swap point: a real physics engine (Jolt, PhysX) can replace this class - Play only uses its public API.
#pragma once

#include <cstdint>
#include <vector>

#include "Vector3.h"

namespace cmmo::world
{
class Scene;
struct Entity;

struct Body
{
	uint32_t id = 0;              // the actor
	Vector3 min, max;             // world-space box
	bool trigger = false;
};

// the colliders one actor has, in world space (also used by the editor to draw them)
void BodiesOf( const Scene& scene, const Entity& e, std::vector<Body>& out );

class PhysicsWorld
{
public:
	static constexpr float kStepHeight = 0.45f;

	void Build( const Scene& scene );   // every visible actor's colliders
	const std::vector<Body>& Bodies() const { return m_bodies; }

	// highest solid top under a capsule at `feet` that it can stand on (<= feet.y + step); -1e9 when none
	float FloorUnder( const Vector3& feet, float radius ) const;
	// push a capsule out of every solid box it overlaps sideways; true when it touched one
	bool PushOut( Vector3& feet, float radius, float height ) const;
	// trigger boxes the capsule overlaps (actor ids, each once)
	void Triggers( const Vector3& feet, float radius, float height, std::vector<uint32_t>& out ) const;

private:
	std::vector<Body> m_bodies;
};
}
