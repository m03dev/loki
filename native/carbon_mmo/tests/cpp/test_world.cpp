// MODULE: tests (world core)
// The engine's world model without any graphics: terrain, scene, level files, Play.  Prints WORLD OK.
#include <cmath>
#include <cstdio>
#include <string>

#include "world/World.h"

using namespace cmmo::world;

static int g_pass = 0, g_fail = 0;
static void Check( const char* name, bool ok, const std::string& detail = "" )
{
	( ok ? g_pass : g_fail )++;
	std::fflush( stdout );
	std::printf( "  [%s] %s%s%s\n", ok ? "PASS" : "FAIL", name, ok || detail.empty() ? "" : " <- ", ok ? "" : detail.c_str() );
}
static std::string F( float v ) { return std::to_string( v ); }

int main()
{
	// ---- terrain
	Scene s;
	const uint32_t tid = s.Create( ActorType::Terrain ).id;
	Check( "a new terrain is flat and covers its size", s.GroundAt( 10, 10 ) == 0.0f && !( [&] { bool f; s.GroundAt( 500, 0, &f ); return f; }() ) );
	Brush b;
	b.mode = Brush::Raise;
	b.radius = 8;
	b.strength = 0.5f;
	for( int i = 0; i < 10; ++i ) s.Find( tid )->terrain->Sculpt( 0, 0, b );
	const float peak = s.GroundAt( 0, 0 ), side = s.GroundAt( 6, 0 );
	Check( "Raise builds a smooth hill", peak > 4 && side > 0.2f && side < peak && s.GroundAt( 20, 0 ) == 0.0f, F( peak ) + " " + F( side ) );
	b.mode = Brush::Smooth;
	b.strength = 1;
	for( int i = 0; i < 20; ++i ) s.Find( tid )->terrain->Sculpt( 0, 0, b );
	Check( "Smooth lowers the peak", s.GroundAt( 0, 0 ) < peak );
	b.mode = Brush::Flatten;
	b.flattenHeight = 2;
	b.radius = 4;
	s.Find( tid )->terrain->Sculpt( -20, -20, b );
	Check( "Flatten pulls the ground to a height", std::fabs( s.GroundAt( -20, -20 ) - 2 ) < 0.05f, F( s.GroundAt( -20, -20 ) ) );
	b.mode = Brush::Paint;
	b.color = Vector3( 1, 1, 1 );
	const uint32_t v0 = s.Find( tid )->terrain->Version();
	s.Find( tid )->terrain->Sculpt( 20, 20, b );
	Check( "Paint colours the ground and bumps the version", s.Find( tid )->terrain->Version() > v0 );
	s.Find( tid )->transform.position.y = 10;
	Check( "ground follows the terrain actor's position", std::fabs( s.GroundAt( -20, -20 ) - 12 ) < 0.05f );
	s.Find( tid )->transform.position.y = 0;
	Vector3 hit;
	Check( "a ray from above hits the hill", s.RaycastTerrain( Vector3( 0, 50, 30 ), Normalize( Vector3( 0, -50, -30 ) ), hit ) &&
											  std::fabs( hit.y - s.GroundAt( hit.x, hit.z ) ) < 0.05f && hit.z < 30, F( hit.x ) + "," + F( hit.y ) + "," + F( hit.z ) );

	// ---- scene + picking + level files
	const uint32_t boxId = s.Create( ActorType::Mesh ).id;            // ids, never references: Create may move the list
	s.Find( boxId )->transform.position = Vector3( 30, 1, 30 );
	s.Find( s.Create( ActorType::PlayerStart ).id )->transform.position = Vector3( 0, 0, 25 );
	const std::string second = s.Create( ActorType::Mesh ).name;
	Check( "names are unique per type", s.Find( boxId )->name == "Shape1" && second == "Shape2", s.Find( boxId )->name + " " + second );
	s.Remove( s.FindByName( "Shape2" )->id );
	Check( "Pick finds the shape the ray goes through", s.Pick( Vector3( 30, 1, 50 ), Vector3( 0, 0, -1 ) ) == boxId );
	Check( "Pick finds the terrain under the cursor", s.Pick( Vector3( 0, 50, 0 ), Vector3( 0, -1, 0 ) ) == tid );
	const std::string path = "/tmp/cmmo_test_level.json";
	std::string err;
	Check( "SaveLevel writes the level", SaveLevel( s, path, &err ), err );
	Scene back;
	Check( "LoadLevel reads it back", LoadLevel( back, path, &err ), err );
	Check( "terrain heights, transforms and props survive", back.Entities().size() == s.Entities().size() &&
															   std::fabs( back.GroundAt( -20, -20 ) - 2 ) < 0.05f &&
															   back.Find( boxId ) && back.Find( boxId )->transform.position.x == 30 &&
															   back.Find( boxId )->props["shape"] == "cube" );
	Scene junk;
	Check( "a file that is not a level is refused", !junk.FromJson( json{ { "format", "other" } }, &err ) && !err.empty() );

	// ---- play: third person on the terrain
	{
		PlaySession play( s, true );
		Check( "Play starts at the Player Start, on the ground", std::fabs( play.PlayerPosition().z - 25 ) < 1e-4f && play.OnGround() );
		PlayInput in;
		in.forward = true;
		for( int i = 0; i < 180; ++i ) play.Tick( 1.0f / 60, in );
		const Vector3 p = play.PlayerPosition();
		Check( "W walks forward (-z) and the feet stay on the hill", p.z < 6 && std::fabs( p.y - s.GroundAt( p.x, p.z ) ) < 0.05f && p.y > 0.3f,
			   F( p.z ) + " " + F( p.y ) );
		in = PlayInput();
		in.jump = true;
		play.Tick( 1.0f / 60, in );
		in.jump = false;
		float top = p.y;
		for( int i = 0; i < 20; ++i ) { play.Tick( 1.0f / 60, in ); top = std::max( top, play.PlayerPosition().y ); }
		for( int i = 0; i < 90; ++i ) play.Tick( 1.0f / 60, in );
		Check( "Space jumps, gravity lands you", top > p.y + 0.5f && play.OnGround() );
		const float yaw0 = play.PlayerYaw();
		in.turnLeft = true;
		for( int i = 0; i < 30; ++i ) play.Tick( 1.0f / 60, in );
		in.turnLeft = false;
		Check( "A turns the character", play.PlayerYaw() > yaw0 + 1.0f );
		const float yaw1 = play.PlayerYaw();
		in.orbit = true;
		in.mouseDX = 200;
		play.Tick( 1.0f / 60, in );
		Check( "left-drag orbits only the camera", play.PlayerYaw() == yaw1 );
		in.orbit = false;
		in.turning = true;
		play.Tick( 1.0f / 60, in );
		Check( "right-drag turns the character", std::fabs( play.PlayerYaw() - yaw1 ) > 0.5f );
		Vector3 eye, target;
		play.CameraEyeTarget( eye, target );
		Check( "the camera sits behind and above, never under the ground", eye.y > target.y - 1 && eye.y >= play.World().GroundAt( eye.x, eye.z ) + 0.39f );
		play.World().Find( boxId )->transform.position.x = 999;
		Check( "Play works on a copy: the level is untouched", s.Find( boxId )->transform.position.x == 30 );
	}

	// ---- creatures
	{
		Scene w;
		w.Create( ActorType::Terrain );
		const uint32_t spId = w.Create( ActorType::CreatureSpawn ).id;
		w.Find( spId )->props["count"] = 4;
		w.Find( spId )->props["wander"] = 5.0;
		w.Find( spId )->props["aggro"] = 8.0;
		w.Create( ActorType::PlayerStart ).transform.position = Vector3( 0, 0, 60 );
		PlaySession play( w, true, 42 );
		Check( "a Creature Spawn makes its creatures", play.Creatures().size() == 4 );
		PlayInput none;
		for( int i = 0; i < 600; ++i ) play.Tick( 1.0f / 60, none );
		bool inRing = true;
		for( const auto& c : play.Creatures() ) inRing &= std::hypot( c.position.x, c.position.z ) <= 5.3f;
		Check( "they wander inside the ring", inRing );
		play.SetPlayerPosition( Vector3( 0, 0, 9 ) );
		for( int i = 0; i < 60; ++i ) play.Tick( 1.0f / 60, none );
		bool chase = false;
		for( const auto& c : play.Creatures() ) chase |= c.state == Creature::Chase;
		const auto log = play.TakeLog();
		Check( "hostile creatures attack when you come close", chase && !log.empty() );
		play.SetPlayerPosition( Vector3( 0, 0, 90 ) );
		for( int i = 0; i < 600; ++i ) play.Tick( 1.0f / 60, none );
		bool home = true;
		for( const auto& c : play.Creatures() ) home &= c.state != Creature::Chase && std::hypot( c.position.x, c.position.z ) < 8;
		Check( "they leash and go home when you run", home );
	}

	std::printf( "\n%d passed, %d failed\n%s\n", g_pass, g_fail, g_fail ? "WORLD FAILED" : "WORLD OK" );
	return g_fail ? 1 : 0;
}
