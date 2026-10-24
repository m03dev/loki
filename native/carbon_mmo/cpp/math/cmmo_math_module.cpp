// MODULE: math
// Standalone Python extension: `import cmmo_math` from any Python 3.10+ process.
#include "math/CarbonMathBindings.h"

PYBIND11_MODULE( cmmo_math, m )
{
	m.doc() = "Carbon math (carbonengine/math) exposed to Python";
	cmmo::BindCarbonMath( m );
}
