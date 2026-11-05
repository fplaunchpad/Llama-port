/* Link-time placeholders for the SSE2 intrinsics used by the MG_SIMD kernel.
 *
 * An [@@builtin] external is emitted inline by the native compiler and these
 * are never called; they exist because a closure that is not fully inlined
 * still carries the symbol's address in its data block, and the linker wants
 * something there. Reaching one at run time means the intrinsic was not
 * expanded, which is a bug rather than a slow path, so they abort.
 */
#include <assert.h>

#define BUILTIN(name) void name(void) { assert(!"[@@builtin] intrinsic was not expanded"); }

BUILTIN(caml_sse2_unreachable)
BUILTIN(caml_sse2_float64x2_add)
BUILTIN(caml_sse2_float64x2_mul)
BUILTIN(caml_float64x2_low_of_float)
BUILTIN(caml_float64x2_low_to_float)
BUILTIN(caml_sse_vec128_low_64_to_high_64)
BUILTIN(caml_sse_vec128_high_64_to_low_64)
