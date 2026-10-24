// MODULE: tests (world core)
// The engine's world model without any graphics: terrain, scene, level files, Play.  Prints WORLD OK.
#include <algorithm>
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
	b.height = 2;
	b.radius = 4;
	s.Find( tid )->terrain->Sculpt( -20, -20, b );
	Check( "Flatten pulls the ground to a height", std::fabs( s.GroundAt( -20, -20 ) - 2 ) < 0.05f, F( s.GroundAt( -20, -20 ) ) );
	b.mode = Brush::Paint;
	b.layer = 3;
	b.radius = 4;
	const uint32_t v0 = s.Find( tid )->terrain->Version();
	s.Find( tid )->terrain->Sculpt( 20, 20, b );
	{
		const Terrain& tr = *s.Find( tid )->terrain;
		const int n = tr.Res() + 1, i = int( ( 20 / tr.Size() + 0.5f ) * tr.Res() + 0.5f );
		const size_t k = size_t( i * n + i );
		int sum = 0;
		for( int l = 0; l < 4; ++l ) sum += tr.Weights()[k * 4 + size_t( l )];
		Check( "Paint moves the layer weights (they still add up to 255)", tr.Version() > v0 && tr.Weights()[k * 4 + 3] > 200 && sum == 255, std::to_string( sum ) );
	}
	s.Find( tid )->transform.position.y = 10;
	Check( "ground follows the terrain actor's position", std::fabs( s.GroundAt( -20, -20 ) - 12 ) < 0.05f );
	s.Find( tid )->transform.position.y = 0;
	Vector3 hit;
	Check( "a ray from above hits the hill", s.RaycastTerrain( Vector3( 0, 50, 30 ), Normalize( Vector3( 0, -50, -30 ) ), hit ) &&
											  std::fabs( hit.y - s.GroundAt( hit.x, hit.z ) ) < 0.05f && hit.z < 30, F( hit.x ) + "," + F( hit.y ) + "," + F( hit.z ) );

	// ---- Terrain3D-style tools
	{
		Terrain g( 64, 128 );
		g.Generate( 7, 30, 30, 5, false );
		float lo = 1e9f, hi = -1e9f;
		for( float h : g.Heights() ) { lo = std::min( lo, h ); hi = std::max( hi, h ); }
		Check( "Generate makes hills and valleys (seeded noise) that fade out at the borders", hi - lo > 10 && std::fabs( g.HeightAt( 63.9f, 0 ) ) < 0.5f, F( lo ) + ".." + F( hi ) );
		Brush r;
		r.mode = Brush::Ramp;
		r.radius = 6;
		r.strength = 1;
		r.rampFrom = Vector3( -20, 0, 0 );
		r.rampTo = Vector3( 20, 0, 0 );
		r.rampFromH = 0;
		r.rampToH = 10;
		Terrain flat( 64, 128 );
		for( float x = -20; x <= 20; x += 2 ) flat.Sculpt( x, 0, r );
		Check( "Ramp builds a slope from where the drag started to where it is", std::fabs( flat.HeightAt( 0, 0 ) - 5 ) < 0.6f && flat.HeightAt( 18, 0 ) > 8, F( flat.HeightAt( 0, 0 ) ) );
		Brush fo;
		fo.mode = Brush::Foliage;
		fo.foliage = FoliageKind::Tree;
		fo.radius = 15;
		fo.density = 1;
		flat.Sculpt( -40, -40, fo );
		const size_t trees = flat.Foliage().size();
		Check( "Foliage paints trees inside the brush, spaced out", trees >= 5 && std::all_of( flat.Foliage().begin(), flat.Foliage().end(),
			[]( const FoliageInstance& f ) { return std::hypot( f.x + 40, f.z + 40 ) <= 15.01f; } ), std::to_string( trees ) );
		fo.mode = Brush::EraseFoliage;
		fo.radius = 30;
		flat.Sculpt( -40, -40, fo );
		Check( "Erase removes them", flat.Foliage().empty() );
		Terrain copy;
		flat.Sculpt( 10, 10, [] { Brush f; f.mode = Brush::Foliage; f.foliage = FoliageKind::Rock; f.radius = 8; f.density = 1; return f; }() );
		Check( "terrain save / load keeps heights, layers and foliage", copy.Load( flat.Save() ) && copy.Foliage().size() == flat.Foliage().size() &&
																		 std::fabs( copy.HeightAt( 0, 0 ) - flat.HeightAt( 0, 0 ) ) < 1e-4f );
	}

	// ---- hierarchy (Godot-style scene tree)
	{
		Scene h;
		const uint32_t parent = h.Create( ActorType::Empty ).id;
		h.Find( parent )->transform.position = Vector3( 10, 0, 0 );
		h.Find( parent )->transform.rotation = Vector3( 0, 90, 0 );
		const uint32_t child = h.Create( ActorType::Mesh, "", parent ).id;
		h.Find( child )->transform.position = Vector3( 0, 0, -5 );
		const Vector3 w = h.WorldPosition( child );
		Check( "a child moves and turns with its parent", std::fabs( w.x - 5 ) < 1e-3f && std::fabs( w.z ) < 1e-3f, F( w.x ) + "," + F( w.z ) );
		Check( "SetParent refuses a cycle", !h.SetParent( parent, child ) );
		Check( "SetParent to the root keeps where it is in the world", h.SetParent( child, 0 ) && Length( h.WorldPosition( child ) - w ) < 1e-3f );
		h.SetParent( child, parent );
		Check( "and back under the parent, still in place", Length( h.WorldPosition( child ) - w ) < 1e-3f && h.Find( child )->parent == parent );
		h.Remove( parent );
		Check( "removing a parent removes its children", h.Entities().empty() );
	}

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

	// ---- the MMO layer: targeting, combat, XP, quests, zones
	{
		Scene w;
		w.Create( ActorType::Terrain );
		const uint32_t sp = w.Create( ActorType::CreatureSpawn ).id;
		w.Find( sp )->transform.position = Vector3( 0, 0, -10 );
		w.Find( sp )->props["count"] = 2;
		w.Find( sp )->props["wander"] = 1.0;
		w.Find( sp )->props["health"] = 20;
		w.Find( sp )->props["hostile"] = false;
		const uint32_t giver = w.Create( ActorType::QuestGiver ).id;
		w.Find( giver )->transform.position = Vector3( 0, 0, 2 );
		w.Find( giver )->props["count"] = 2;
		const uint32_t zone = w.Create( ActorType::Zone ).id;
		w.Find( zone )->props["zone"] = "Test Glade";
		PlaySession p( w, true, 9 );
		Check( "entering a zone shows its name", p.zone == "Test Glade" && p.zoneBanner > 0 );
		PlayInput in;
		in.interact = true;
		p.Tick( 1.0f / 60, in );
		Check( "F next to the quest giver opens the dialog", p.talkingTo == 0 && p.quests[0].state == Quest::Offered );
		Check( "accept the quest", p.AcceptQuest( 0 ) && p.quests[0].state == Quest::Active );
		int kills = 0;
		for( int round = 0; round < 2; ++round )
		{
			in = PlayInput();
			in.tabTarget = true;
			p.Tick( 1.0f / 60, in );
			const int t = p.target;
			if( t < 0 ) break;
			p.SetPlayerPosition( p.Creatures()[size_t( t )].position + Vector3( 0, 0, 1.5f ) );
			for( int k = 0; k < 600 && p.Creatures()[size_t( t )].state != Creature::Dead; ++k )
			{
				in = PlayInput();
				in.ability = ( k % 2 ) ? 1 : 2;
				p.Tick( 1.0f / 30, in );
			}
			kills += p.Creatures()[size_t( t )].state == Creature::Dead;
		}
		Check( "Tab targets a creature; abilities kill it", kills == 2, std::to_string( kills ) );
		Check( "kills count for the quest and give XP", p.quests[0].state == Quest::Ready && ( p.xp > 0 || p.level > 1 ) );
		p.SetPlayerPosition( Vector3( 0, 0, 3 ) );
		const int lvl = p.level, xp = p.xp;
		Check( "turning the quest in rewards XP", p.CompleteQuest( 0 ) && ( p.level > lvl || p.xp > xp ) );
		for( int k = 0; k < 30 * 20; ++k ) p.Tick( 1.0f / 30, PlayInput() );
		Check( "dead creatures respawn", p.Creatures()[0].state != Creature::Dead );
	}

	std::printf( "\n%d passed, %d failed\n%s\n", g_pass, g_fail, g_fail ? "WORLD FAILED" : "WORLD OK" );
	return g_fail ? 1 : 0;
}
