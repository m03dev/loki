// MODULE: world.gameplay
#include "world/Gameplay.h"

#include <algorithm>
#include <cmath>

namespace cmmo::world
{
namespace
{
constexpr float kPi = 3.14159265358979f;

Vector3 V3( const json& c, const char* key, const Vector3& d )
{
	const auto it = c.find( key );
	if( it == c.end() || !it->is_array() || it->size() != 3 ) return d;
	return Vector3( ( *it )[0].get<float>(), ( *it )[1].get<float>(), ( *it )[2].get<float>() );
}

Entity* Self( PlaySession& s, uint32_t id ) { return s.World().Find( id ); }

// ---- Motion -------------------------------------------------------------------------------------------------------
class Rotator : public Behaviour
{
	void Tick( PlaySession& s, float, float dt ) override
	{
		if( Entity* e = Self( s, actor ) ) e->transform.rotation += V3( config, "speed", Vector3( 0, 45, 0 ) ) * dt;
	}
};

class Bobber : public Behaviour
{
	Vector3 base;
	void Start( PlaySession& s ) override
	{
		if( Entity* e = Self( s, actor ) ) base = e->transform.position;
	}
	void Tick( PlaySession& s, float t, float ) override
	{
		const float h = config.value( "height", 0.5f ), period = std::max( 0.05f, config.value( "period", 2.0f ) );
		if( Entity* e = Self( s, actor ) ) e->transform.position.y = base.y + h * 0.5f * ( 1.0f - std::cos( 2 * kPi * t / period ) );
	}
};

class Mover : public Behaviour
{
	Vector3 base;
	float clock = 0;
	bool running = true;
	void Start( PlaySession& s ) override
	{
		if( Entity* e = Self( s, actor ) ) base = e->transform.position;
		running = !config.value( "onTrigger", false );
	}
	void Enter( PlaySession& ) override { running = true; }
	void Tick( PlaySession& s, float, float dt ) override
	{
		if( !running ) return;
		clock += dt;
		const float dur = std::max( 0.05f, config.value( "duration", 2.0f ) );
		float f = clock / dur;
		if( config.value( "pingPong", true ) ) f = 0.5f - 0.5f * std::cos( kPi * f );   // eased there and back, forever
		else f = std::min( 1.0f, f );
		if( Entity* e = Self( s, actor ) ) e->transform.position = base + V3( config, "offset", Vector3( 0, 3, 0 ) ) * f;
	}
};

// ---- Gameplay -----------------------------------------------------------------------------------------------------
class TriggerEvent : public Behaviour
{
	int fired = 0;
	void Enter( PlaySession& s ) override
	{
		if( config.value( "once", false ) && fired ) return;
		++fired;
		const std::string action = config.value( "action", std::string( "message" ) );
		const std::string text = config.value( "text", std::string() );
		const float amount = config.value( "amount", 10.0f );
		if( !text.empty() ) s.Message( text );
		if( action == "heal" ) s.Heal( amount );
		else if( action == "damage" ) s.Damage( amount );
		else if( action == "xp" ) s.AddXp( int( amount ) );
		else if( action == "teleport" || action == "toggle" )
		{
			Entity* target = s.World().FindByName( config.value( "target", std::string() ) );
			if( !target ) { s.Message( "Trigger Event: no actor named \"" + config.value( "target", std::string() ) + "\"" ); return; }
			if( action == "toggle" ) target->visible = !target->visible;
			else s.SetPlayerPosition( s.World().WorldPosition( target->id ) );
		}
	}
};

class Pickup : public Behaviour
{
	float away = 0;
	void Enter( PlaySession& s ) override
	{
		Entity* e = Self( s, actor );
		if( !e || !e->visible ) return;
		const int xp = config.value( "xp", 25 );
		const float heal = config.value( "heal", 0.0f );
		const std::string text = config.value( "message", std::string() );
		if( !text.empty() ) s.Message( text );
		if( xp ) s.AddXp( xp );
		if( heal > 0 ) s.Heal( heal );
		e->visible = false;
		away = config.value( "respawn", 0.0f );
	}
	void Tick( PlaySession& s, float, float dt ) override
	{
		if( away <= 0 ) return;
		away -= dt;
		if( away <= 0 )
			if( Entity* e = Self( s, actor ) ) e->visible = true;
	}
};

template <class T> std::function<std::unique_ptr<Behaviour>()> Make()
{
	return [] { return std::unique_ptr<Behaviour>( new T() ); };
}

std::vector<ComponentInfo> RegisterBuiltins()
{
	return {
		{ "BoxCollider", "Box Collider", "A solid box (or a trigger): blocks the player and creatures, and can be stood on.", "Physics", "box",
		  { { "size", { 1.0, 1.0, 1.0 } }, { "offset", { 0.0, 0.5, 0.0 } }, { "trigger", false } }, nullptr },
		{ "SphereCollider", "Sphere Collider", "A solid ball (collides as the box around it) or a trigger.", "Physics", "sphere",
		  { { "radius", 0.5 }, { "offset", { 0.0, 0.5, 0.0 } }, { "trigger", false } }, nullptr },
		{ "Rotator", "Rotator", "Spins the actor, degrees per second around X / Y / Z.", "Motion", "rotate", { { "speed", { 0.0, 45.0, 0.0 } } }, Make<Rotator>() },
		{ "Bobber", "Bobber", "Floats the actor up and down.", "Motion", "bob", { { "height", 0.5 }, { "period", 2.0 } }, Make<Bobber>() },
		{ "Mover", "Mover", "Slides the actor by an offset and back (platforms, doors, lifts). On Trigger: waits until the player enters it.",
		  "Motion", "move", { { "offset", { 0.0, 3.0, 0.0 } }, { "duration", 2.0 }, { "pingPong", true }, { "onTrigger", false } }, Make<Mover>() },
		{ "TriggerEvent", "Trigger Event",
		  "When the player enters this actor's trigger: action = message, heal, damage, xp, teleport (to the target actor) or toggle "
		  "(show / hide the target actor). Needs a trigger: a Trigger Box actor, or a collider with trigger on.",
		  "Gameplay", "bolt", { { "action", "message" }, { "text", "Something happens." }, { "amount", 10.0 }, { "target", "" }, { "once", false } }, Make<TriggerEvent>() },
		{ "Pickup", "Pickup", "Touch to collect: XP and / or health, a message; disappears (comes back after Respawn seconds if set).", "Gameplay", "gem",
		  { { "xp", 25 }, { "heal", 0.0 }, { "message", "" }, { "radius", 1.2 }, { "respawn", 0.0 } }, Make<Pickup>() },
	};
}
}

const std::vector<ComponentInfo>& ComponentTypes()
{
	static const std::vector<ComponentInfo> types = RegisterBuiltins();
	return types;
}

const ComponentInfo* FindComponentType( const std::string& type )
{
	for( const auto& c : ComponentTypes() )
		if( c.type == type ) return &c;
	return nullptr;
}

json MakeComponent( const std::string& type )
{
	const ComponentInfo* info = FindComponentType( type );
	json c = info ? info->defaults : json::object();
	c["type"] = type;
	return c;
}
}
