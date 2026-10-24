// MODULE: render
#include "render/Renderer.h"

namespace cmmo
{
std::vector<std::string> RenderConfig::Validate() const
{
	std::vector<std::string> problems;
	if( width < 64 || width > 16384 )
	{
		problems.push_back( "width must be between 64 and 16384" );
	}
	if( height < 64 || height > 16384 )
	{
		problems.push_back( "height must be between 64 and 16384" );
	}
	const float channels[] = { clear_color.r, clear_color.g, clear_color.b, clear_color.a };
	for( float c : channels )
	{
		if( c < 0.0f || c > 1.0f )
		{
			problems.push_back( "clear_color channels must be in [0, 1]" );
			break;
		}
	}
	if( max_frames < 0 )
	{
		problems.push_back( "max_frames must be >= 0" );
	}
	return problems;
}
}
