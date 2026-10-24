// MODULE: editor.theme
#include "editor/Theme.h"

#include <cstdlib>
#include <filesystem>
#include <vector>

#include "imgui_internal.h"

namespace fs = std::filesystem;

namespace cmmo::editor::ui
{
namespace
{
Fonts g_fonts;

ImU32 Lerp( ImU32 a, ImU32 b, float t ) { return ImGui::GetColorU32( ImLerp( ImGui::ColorConvertU32ToFloat4( a ), ImGui::ColorConvertU32ToFloat4( b ), t ) ); }
ImU32 Shade( ImU32 c, float k )
{
	ImVec4 v = ImGui::ColorConvertU32ToFloat4( c );
	return ImGui::GetColorU32( ImVec4( ImMin( 1.0f, v.x * k ), ImMin( 1.0f, v.y * k ), ImMin( 1.0f, v.z * k ), v.w ) );
}

// the bevel: soft vertical gradient, light top edge, dark bottom edge, rounded
void Bevel( ImDrawList* dl, ImVec2 a, ImVec2 b, ImU32 base, float rounding, bool pressed )
{
	const ImU32 top = pressed ? Shade( base, 0.82f ) : Shade( base, 1.18f ), bottom = pressed ? Shade( base, 1.05f ) : Shade( base, 0.86f );
	dl->AddRectFilled( a, b, bottom, rounding );
	dl->AddRectFilledMultiColor( ImVec2( a.x + 1, a.y + 1 ), ImVec2( b.x - 1, ( a.y + b.y ) * 0.5f + 1 ), top, top, base, base );
	dl->AddRectFilled( ImVec2( a.x + 1, ( a.y + b.y ) * 0.5f ), ImVec2( b.x - 1, b.y - 1 ), Lerp( base, bottom, 0.5f ), rounding, ImDrawFlags_RoundCornersBottom );
	dl->AddLine( ImVec2( a.x + rounding, a.y + 0.5f ), ImVec2( b.x - rounding, a.y + 0.5f ), pressed ? IM_COL32( 0, 0, 0, 70 ) : IM_COL32( 255, 255, 255, 38 ) );
	dl->AddRect( a, b, IM_COL32( 0, 0, 0, 110 ), rounding );
}

std::string FindFonts( const char* exePath )
{
	std::vector<fs::path> where;
	if( const char* env = std::getenv( "CMMO_FONTS" ) ) where.emplace_back( env );
#ifdef CMMO_SOURCE_DIR
	where.emplace_back( fs::path( CMMO_SOURCE_DIR ) / "third_party" / "fonts" );
#endif
	if( exePath ) where.push_back( fs::path( exePath ).parent_path() / "fonts" );
	for( const auto& p : where )
	{
		std::error_code ec;
		if( fs::exists( p / "IBMPlexSans-Regular.ttf", ec ) && fs::exists( p / "fa-solid-900.ttf", ec ) ) return p.string();
	}
	return "";
}
}

const Fonts& GetFonts() { return g_fonts; }
void PushFont( ImFont* f ) { ImGui::PushFont( f, f ? f->LegacySize : 0.0f ); }

std::string Setup( const char* exePath )
{
	ImGuiIO& io = ImGui::GetIO();
	const std::string dir = FindFonts( exePath );
	if( !dir.empty() )
	{
		static const ImWchar icons[] = { ICON_MIN_FA, ICON_MAX_16_FA, 0 };
		auto load = [&]( const char* file, float size, bool withIcons ) {
			ImFontConfig cfg;
			cfg.OversampleH = 2;
			cfg.PixelSnapH = false;
			ImFont* f = io.Fonts->AddFontFromFileTTF( ( fs::path( dir ) / file ).string().c_str(), size, &cfg );
			if( f && withIcons )
			{
				ImFontConfig ic;
				ic.MergeMode = true;
				ic.GlyphMinAdvanceX = size * 1.05f;
				ic.GlyphOffset = ImVec2( 0, 0.5f );
				io.Fonts->AddFontFromFileTTF( ( fs::path( dir ) / "fa-solid-900.ttf" ).string().c_str(), size * 0.86f, &ic, icons );
			}
			return f;
		};
		g_fonts.body = load( "IBMPlexSans-Regular.ttf", 15.0f, true );
		g_fonts.bold = load( "IBMPlexSans-SemiBold.ttf", 15.0f, true );
		g_fonts.big = load( "IBMPlexSans-SemiBold.ttf", 24.0f, true );
		g_fonts.huge = load( "IBMPlexSans-SemiBold.ttf", 34.0f, false );
		io.FontDefault = g_fonts.body;
	}
	if( !g_fonts.body )
	{
		g_fonts.body = g_fonts.bold = g_fonts.big = g_fonts.huge = io.Fonts->AddFontDefault();
	}

	ImGuiStyle& s = ImGui::GetStyle();
	ImGui::StyleColorsDark( &s );
	s.WindowRounding = 6;
	s.ChildRounding = 5;
	s.FrameRounding = 5;
	s.PopupRounding = 6;
	s.GrabRounding = 5;
	s.TabRounding = 5;
	s.ScrollbarRounding = 8;
	s.WindowBorderSize = 1;
	s.FrameBorderSize = 1;
	s.PopupBorderSize = 1;
	s.TabBorderSize = 0;
	s.WindowPadding = ImVec2( 10, 10 );
	s.FramePadding = ImVec2( 8, 5 );
	s.ItemSpacing = ImVec2( 8, 6 );
	s.ItemInnerSpacing = ImVec2( 6, 4 );
	s.IndentSpacing = 16;
	s.ScrollbarSize = 11;
	s.GrabMinSize = 10;
	s.SeparatorTextBorderSize = 1;
	s.SeparatorTextPadding = ImVec2( 6, 4 );
	s.WindowMenuButtonPosition = ImGuiDir_None;
	s.DockingSeparatorSize = 3;

	// LOKI Forge's palette: graphite panels, a blue accent
	ImVec4* c = s.Colors;
	auto rgb = []( int r, int g, int b, float a = 1 ) { return ImVec4( r / 255.0f, g / 255.0f, b / 255.0f, a ); };
	c[ImGuiCol_Text] = rgb( 220, 223, 228 );
	c[ImGuiCol_TextDisabled] = rgb( 128, 134, 143 );
	c[ImGuiCol_WindowBg] = rgb( 35, 36, 39 );
	c[ImGuiCol_ChildBg] = rgb( 29, 30, 33 );
	c[ImGuiCol_PopupBg] = rgb( 40, 41, 45, 0.98f );
	c[ImGuiCol_Border] = rgb( 18, 18, 20 );
	c[ImGuiCol_BorderShadow] = rgb( 0, 0, 0, 0 );
	c[ImGuiCol_FrameBg] = rgb( 26, 27, 30 );
	c[ImGuiCol_FrameBgHovered] = rgb( 33, 35, 39 );
	c[ImGuiCol_FrameBgActive] = rgb( 38, 41, 47 );
	c[ImGuiCol_TitleBg] = rgb( 30, 31, 34 );
	c[ImGuiCol_TitleBgActive] = rgb( 30, 31, 34 );
	c[ImGuiCol_MenuBarBg] = rgb( 30, 31, 34 );
	c[ImGuiCol_ScrollbarBg] = rgb( 30, 31, 34, 0 );
	c[ImGuiCol_ScrollbarGrab] = rgb( 70, 73, 80 );
	c[ImGuiCol_ScrollbarGrabHovered] = rgb( 90, 94, 102 );
	c[ImGuiCol_CheckMark] = rgb( 76, 156, 235 );
	c[ImGuiCol_SliderGrab] = rgb( 47, 127, 208 );
	c[ImGuiCol_SliderGrabActive] = rgb( 76, 156, 235 );
	c[ImGuiCol_Button] = rgb( 58, 60, 65 );
	c[ImGuiCol_ButtonHovered] = rgb( 71, 74, 80 );
	c[ImGuiCol_ButtonActive] = rgb( 47, 127, 208 );
	c[ImGuiCol_Header] = rgb( 47, 127, 208, 0.45f );
	c[ImGuiCol_HeaderHovered] = rgb( 255, 255, 255, 0.06f );
	c[ImGuiCol_HeaderActive] = rgb( 47, 127, 208, 0.65f );
	c[ImGuiCol_Separator] = rgb( 255, 255, 255, 0.07f );
	c[ImGuiCol_SeparatorHovered] = rgb( 47, 127, 208, 0.7f );
	c[ImGuiCol_ResizeGrip] = rgb( 0, 0, 0, 0 );
	c[ImGuiCol_Tab] = rgb( 30, 31, 34 );
	c[ImGuiCol_TabHovered] = rgb( 50, 52, 58 );
	c[ImGuiCol_TabSelected] = rgb( 35, 36, 39 );
	c[ImGuiCol_TabSelectedOverline] = rgb( 47, 127, 208 );
	c[ImGuiCol_TabDimmed] = rgb( 30, 31, 34 );
	c[ImGuiCol_TabDimmedSelected] = rgb( 35, 36, 39 );
	c[ImGuiCol_DockingPreview] = rgb( 47, 127, 208, 0.5f );
	c[ImGuiCol_DockingEmptyBg] = rgb( 20, 20, 22 );
	c[ImGuiCol_TableHeaderBg] = rgb( 43, 44, 47 );
	c[ImGuiCol_TextSelectedBg] = rgb( 47, 127, 208, 0.4f );
	c[ImGuiCol_NavCursor] = rgb( 76, 156, 235 );
	return dir;
}

void Tip( const char* name, const char* what )
{
	if( !ImGui::IsItemHovered( ImGuiHoveredFlags_DelayShort | ImGuiHoveredFlags_AllowWhenDisabled ) ) return;
	ImGui::BeginTooltip();
	PushFont( g_fonts.bold );
	ImGui::TextUnformatted( name );
	ImGui::PopFont();
	if( what && *what )
	{
		ImGui::PushTextWrapPos( ImGui::GetFontSize() * 22 );
		ImGui::TextDisabled( "%s", what );
		ImGui::PopTextWrapPos();
	}
	ImGui::EndTooltip();
}

bool ToolButton( const char* icon, const char* name, const char* what, bool active, float width, ImU32 tint )
{
	const float h = ImGui::GetFrameHeight() + 4;
	const float w = width > 0 ? width : h + 2;
	ImGui::PushID( name );
	const bool clicked = ImGui::InvisibleButton( "##tb", ImVec2( w, h ) );
	const bool hovered = ImGui::IsItemHovered(), held = ImGui::IsItemActive();
	const ImVec2 a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
	ImDrawList* dl = ImGui::GetWindowDrawList();
	const bool disabled = ( ImGui::GetItemFlags() & ImGuiItemFlags_Disabled ) != 0;
	ImU32 base = active ? ( tint ? tint : col::Accent ) : hovered ? IM_COL32( 74, 77, 84, 255 ) : IM_COL32( 56, 58, 63, 255 );
	Bevel( dl, a, b, base, 5.0f, held );
	const ImVec2 ts = ImGui::CalcTextSize( icon );
	ImU32 fg = disabled ? col::Dim : active ? IM_COL32( 255, 255, 255, 255 ) : tint ? tint : col::Text;
	dl->AddText( ImVec2( a.x + ( w - ts.x ) * 0.5f, a.y + ( h - ts.y ) * 0.5f ), fg, icon );
	Tip( name, what );
	ImGui::PopID();
	return clicked;
}

bool WideButton( const char* icon, const char* label, const char* what, bool active )
{
	ImGui::PushID( label );
	const float h = ImGui::GetFrameHeight() + 6;
	const bool clicked = ImGui::InvisibleButton( "##wb", ImVec2( ImGui::GetContentRegionAvail().x, h ) );
	const bool hovered = ImGui::IsItemHovered(), held = ImGui::IsItemActive();
	const ImVec2 a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
	ImDrawList* dl = ImGui::GetWindowDrawList();
	Bevel( dl, a, b, active ? col::Accent : hovered ? IM_COL32( 70, 73, 80, 255 ) : IM_COL32( 52, 54, 59, 255 ), 5.0f, held );
	const float pad = 10;
	const ImVec2 is = ImGui::CalcTextSize( icon );
	dl->AddText( ImVec2( a.x + pad, a.y + ( h - is.y ) * 0.5f ), active ? IM_COL32( 255, 255, 255, 255 ) : IM_COL32( 140, 190, 245, 255 ), icon );
	const ImVec2 ls = ImGui::CalcTextSize( label );
	dl->AddText( ImVec2( a.x + pad + ImGui::GetFontSize() * 1.6f, a.y + ( h - ls.y ) * 0.5f ), col::Text, label );
	if( what ) Tip( label, what );
	ImGui::PopID();
	return clicked;
}

void ToolbarBackground( float height )
{
	ImDrawList* dl = ImGui::GetWindowDrawList();
	const ImVec2 a = ImGui::GetCursorScreenPos();
	const ImVec2 b( a.x + ImGui::GetContentRegionAvail().x, a.y + height );
	dl->AddRectFilledMultiColor( a, b, IM_COL32( 46, 48, 52, 255 ), IM_COL32( 46, 48, 52, 255 ), IM_COL32( 36, 37, 41, 255 ), IM_COL32( 36, 37, 41, 255 ) );
	dl->AddLine( a, ImVec2( b.x, a.y ), IM_COL32( 255, 255, 255, 18 ) );
	dl->AddLine( ImVec2( a.x, b.y ), b, IM_COL32( 0, 0, 0, 140 ) );
}

void Section( const char* icon, const char* title )
{
	ImGui::Spacing();
	PushFont( g_fonts.bold );
	ImGui::PushStyleColor( ImGuiCol_Text, IM_COL32( 140, 190, 245, 255 ) );
	ImGui::TextUnformatted( icon );
	ImGui::PopStyleColor();
	ImGui::SameLine();
	ImGui::TextUnformatted( title );
	ImGui::PopFont();
	const ImVec2 p = ImGui::GetCursorScreenPos();
	ImGui::GetWindowDrawList()->AddLine( ImVec2( p.x, p.y - 2 ), ImVec2( p.x + ImGui::GetContentRegionAvail().x, p.y - 2 ), IM_COL32( 255, 255, 255, 16 ) );
	ImGui::Spacing();
}

void Label( const char* text )
{
	ImGui::AlignTextToFramePadding();
	ImGui::TextUnformatted( text );
	ImGui::SameLine( ImGui::GetFontSize() * 6.4f );
	ImGui::SetNextItemWidth( -FLT_MIN );
}

bool AxisField( const char* label, float* v, float speed, bool* committed )
{
	static const ImU32 axis[3] = { IM_COL32( 214, 76, 66, 255 ), IM_COL32( 103, 182, 72, 255 ), IM_COL32( 64, 128, 222, 255 ) };
	bool changed = false;
	ImGui::PushID( label );
	ImGui::AlignTextToFramePadding();
	ImGui::TextUnformatted( label );
	ImGui::SameLine( ImGui::GetFontSize() * 6.4f );
	const float full = ImGui::GetContentRegionAvail().x, each = ( full - 2 * ImGui::GetStyle().ItemInnerSpacing.x ) / 3.0f;
	for( int i = 0; i < 3; ++i )
	{
		if( i ) ImGui::SameLine( 0, ImGui::GetStyle().ItemInnerSpacing.x );
		ImGui::PushID( i );
		ImGui::SetNextItemWidth( each );
		const ImVec2 a = ImGui::GetCursorScreenPos();
		changed |= ImGui::DragFloat( "##v", &v[i], speed, 0, 0, "%.2f" );
		if( committed && ImGui::IsItemDeactivatedAfterEdit() ) *committed = true;
		ImGui::GetWindowDrawList()->AddRectFilled( ImVec2( a.x, a.y + 2 ), ImVec2( a.x + 3, a.y + ImGui::GetFrameHeight() - 2 ), axis[i], 2 );
		ImGui::PopID();
	}
	ImGui::PopID();
	return changed;
}

void Bar( const ImVec2& pos, const ImVec2& size, float frac, ImU32 fill, const char* text, ImDrawList* dl )
{
	if( !dl ) dl = ImGui::GetWindowDrawList();
	frac = ImClamp( frac, 0.0f, 1.0f );
	const ImVec2 b( pos.x + size.x, pos.y + size.y );
	dl->AddRectFilled( pos, b, IM_COL32( 12, 12, 14, 220 ), 4 );
	if( frac > 0 )
	{
		const ImVec2 e( pos.x + size.x * frac, b.y );
		dl->AddRectFilledMultiColor( ImVec2( pos.x + 1, pos.y + 1 ), ImVec2( e.x - 1, b.y - 1 ), Shade( fill, 1.25f ), Shade( fill, 1.25f ), Shade( fill, 0.8f ), Shade( fill, 0.8f ) );
	}
	dl->AddRect( pos, b, IM_COL32( 0, 0, 0, 200 ), 4 );
	dl->AddLine( ImVec2( pos.x + 3, pos.y + 1.5f ), ImVec2( b.x - 3, pos.y + 1.5f ), IM_COL32( 255, 255, 255, 30 ) );
	if( text )
	{
		const ImVec2 ts = ImGui::CalcTextSize( text );
		const ImVec2 tp( pos.x + ( size.x - ts.x ) * 0.5f, pos.y + ( size.y - ts.y ) * 0.5f );
		dl->AddText( ImVec2( tp.x + 1, tp.y + 1 ), IM_COL32( 0, 0, 0, 200 ), text );
		dl->AddText( tp, IM_COL32( 245, 245, 245, 255 ), text );
	}
}
}
