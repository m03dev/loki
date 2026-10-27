// MODULE: world.physics
#include "world/Physics.h"

#include <algorithm>
#include <cmath>

#include "Matrix.h"
#include "world/World.h"

namespace cmmo::world
{
namespace
{
Vector3 V3( const json& v, const Vector3& d )
{
	if( !v.is_array() || v.size() != 3 ) return d;
	return Vector3( v[0].get<float>(), v[1].get<float>(), v[2].get<float>() );
}

// a local box (lo..hi) through the actor's world matrix -> the world box that encloses it
void AddBox( const Matrix& W, const Vector3& lo, const Vector3& hi, uint32_t id, bool trigger, std::vector<Body>& out )
{
	Body b;
	b.id = id;
	b.trigger = trigger;
	b.min = Vector3( 1e30f, 1e30f, 1e30f );
	b.max = Vector3( -1e30f, -1e30f, -1e30f );
	for( int k = 0; k < 8; ++k )
	{
		const Vector3 c( k & 1 ? hi.x : lo.x, k & 2 ? hi.y : lo.y, k & 4 ? hi.z : lo.z );
		const Vector3 p = TransformCoord( c, W );
		b.min = Vector3( std::min( b.min.x, p.x ), std::min( b.min.y, p.y ), std::min( b.min.z, p.z ) );
		b.max = Vector3( std::max( b.max.x, p.x ), std::max( b.max.y, p.y ), std::max( b.max.z, p.z ) );
	}
	out.push_back( b );
}

// does a vertical capsule (as a cylinder) overlap the box sideways? (distance from its axis to the box's XZ rectangle)
bool OverlapXZ( const Body& b, const Vector3& p, float r )
{
	const float cx = std::max( b.min.x, std::min( p.x, b.max.x ) ), cz = std::max( b.min.z, std::min( p.z, b.max.z ) );
	const float dx = p.x - cx, dz = p.z - cz;
	return dx * dx + dz * dz < r * r;
}
}

void BodiesOf( const Scene& scene, const Entity& e, std::vector<Body>& out )
{
	const Matrix W = scene.WorldMatrix( e.id );
	if( e.type == ActorType::Mesh && e.props.value( "collision", true ) )
	{
		// shapes sit on their pivot: a unit box from y 0 to 1 (a plane is a thin slab)
		const bool plane = e.props.value( "shape", std::string( "cube" ) ) == "plane";
		AddBox( W, Vector3( -0.5f, plane ? -0.05f : 0.0f, -0.5f ), Vector3( 0.5f, plane ? 0.0f : 1.0f, 0.5f ), e.id, false, out );
	}
	if( e.type == ActorType::TriggerBox )
	{
		const Vector3 s = V3( e.props.value( "size", json() ), Vector3( 2, 2, 2 ) ) * 0.5f;
		// trigger boxes ignore rotation and scale like the editor draws them: centred, sized by "size"
		const Vector3 c = scene.WorldPosition( e.id );
		out.push_back( { e.id, c - s, c + s, true } );
	}
	for( const auto& c : e.components )
	{
		const std::string type = c.value( "type", std::string() );
		const bool trig = c.value( "trigger", false );
		const Vector3 off = V3( c.value( "offset", json() ), Vector3( 0, 0, 0 ) );
		if( type == "BoxCollider" )
		{
			const Vector3 h = V3( c.value( "size", json() ), Vector3( 1, 1, 1 ) ) * 0.5f;
			AddBox( W, off - h, off + h, e.id, trig, out );
		}
		else if( type == "SphereCollider" )
		{
			const float r = c.value( "radius", 0.5f );
			AddBox( W, off - Vector3( r, r, r ), off + Vector3( r, r, r ), e.id, trig, out );
		}
		else if( type == "Pickup" )
		{
			const float r = c.value( "radius", 1.2f );
			AddBox( W, Vector3( -r, -r * 0.5f, -r ), Vector3( r, r * 1.5f, r ), e.id, true, out );
		}
	}
}

void PhysicsWorld::Build( const Scene& scene )
{
	m_bodies.clear();
	for( const auto& e : scene.Entities() )
		if( scene.Visible( e.id ) ) BodiesOf( scene, e, m_bodies );
}

float PhysicsWorld::FloorUnder( const Vector3& feet, float radius ) const
{
	float best = -1e9f;
	for( const auto& b : m_bodies )
		if( !b.trigger && b.max.y <= feet.y + kStepHeight && b.max.y > best && OverlapXZ( b, feet, radius * 0.7f ) ) best = b.max.y;
	return best;
}

bool PhysicsWorld::PushOut( Vector3& feet, float radius, float height ) const
{
	bool touched = false;
	for( int pass = 0; pass < 2; ++pass )   // a corner between two boxes needs a second pass
		for( const auto& b : m_bodies )
		{
			if( b.trigger ) continue;
			if( feet.y + height <= b.min.y || feet.y >= b.max.y - kStepHeight ) continue;   // above it, or a step to climb
			if( !OverlapXZ( b, feet, radius ) ) continue;
			const float cx = std::max( b.min.x, std::min( feet.x, b.max.x ) ), cz = std::max( b.min.z, std::min( feet.z, b.max.z ) );
			float dx = feet.x - cx, dz = feet.z - cz;
			const float d = std::sqrt( dx * dx + dz * dz );
			if( d > 1e-4f )
			{
				feet.x = cx + dx / d * radius;
				feet.z = cz + dz / d * radius;
			}
			else   // the axis is inside the box: leave by the nearest side
			{
				const float l = feet.x - b.min.x, r = b.max.x - feet.x, n = feet.z - b.min.z, f = b.max.z - feet.z;
				const float m = std::min( std::min( l, r ), std::min( n, f ) );
				if( m == l ) feet.x = b.min.x - radius;
				else if( m == r ) feet.x = b.max.x + radius;
				else if( m == n ) feet.z = b.min.z - radius;
				else feet.z = b.max.z + radius;
			}
			touched = true;
		}
	return touched;
}

void PhysicsWorld::Triggers( const Vector3& feet, float radius, float height, std::vector<uint32_t>& out ) const
{
	out.clear();
	for( const auto& b : m_bodies )
	{
		if( !b.trigger || feet.y + height < b.min.y || feet.y > b.max.y || !OverlapXZ( b, feet, radius ) ) continue;
		if( std::find( out.begin(), out.end(), b.id ) == out.end() ) out.push_back( b.id );
	}
}
}
