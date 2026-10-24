// MODULE: editor.theme
// The editor's look: IBM Plex Sans + Font Awesome icons rasterised at the display's real pixel density (Retina),
// LOKI Forge's dark palette, bevelled buttons and toolbars (a light top edge, a dark bottom edge, a soft gradient).
// Every icon button has a hover tooltip (name + what it does).
#pragma once

#include <string>

#include "IconsFontAwesome6.h"
#include "imgui.h"

namespace cmmo::editor::ui
{
struct Fonts
{
	ImFont* body = nullptr;     // 15 px, with icons
	ImFont* bold = nullptr;     // 15 px semibold, with icons
	ImFont* big = nullptr;      // 24 px semibold (HUD, banners)
	ImFont* huge = nullptr;     // 34 px semibold (zone names)
};
const Fonts& GetFonts();
void PushFont( ImFont* f );   // at the size it was loaded at (ImGui 1.92 fonts are size-free)
// Loads the fonts (searching CMMO_FONTS, the source tree and next to the executable) and applies the theme.
// Returns the folder the fonts came from ("" = ImGui's built-in font, still themed).
std::string Setup( const char* exePath );

namespace col
{
constexpr ImU32 Accent = IM_COL32( 47, 127, 208, 255 );
constexpr ImU32 AccentHi = IM_COL32( 76, 156, 235, 255 );
constexpr ImU32 Play = IM_COL32( 61, 200, 120, 255 );
constexpr ImU32 Stop = IM_COL32( 220, 72, 62, 255 );
constexpr ImU32 Text = IM_COL32( 220, 223, 228, 255 );
constexpr ImU32 Dim = IM_COL32( 140, 146, 155, 255 );
constexpr ImU32 Gold = IM_COL32( 240, 196, 70, 255 );
}

// bevelled icon (+ optional label) button. `active` = toggled on (accent). Tooltip shown on hover.
bool ToolButton( const char* icon, const char* name, const char* what, bool active = false, float width = 0, ImU32 tint = 0 );
// a wide bevelled button with icon + label (panels)
bool WideButton( const char* icon, const char* label, const char* what = nullptr, bool active = false );
// the gradient strip behind a toolbar row (call at the row's start, height in px)
void ToolbarBackground( float height );
// section title with an icon, semibold
void Section( const char* icon, const char* title );
// Unreal-style X / Y / Z drag fields (red / green / blue tabs). Returns true while changing.
bool AxisField( const char* label, float* v, float speed, bool* committed );
void Tip( const char* name, const char* what );
// a property row: the label on the left (same column as AxisField), the next widget fills the rest
void Label( const char* text );
// a horizontal bar (health, XP, cooldowns) with text centred
void Bar( const ImVec2& pos, const ImVec2& size, float frac, ImU32 fill, const char* text, ImDrawList* dl = nullptr );
}
