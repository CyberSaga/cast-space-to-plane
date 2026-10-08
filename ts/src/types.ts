/** Vector and matrix aliases of the port (contract §5.4.2 "Array conventions"): row-major nested tuples,
 * identical to their document encoding. */

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];
export type Vec4 = [number, number, number, number];
/** 3×3, rows. */
export type Mat3 = [Vec3, Vec3, Vec3];
/** 3×4 (`P`), rows. */
export type Mat34 = [Vec4, Vec4, Vec4];
/** 4×4 (`M`), rows. */
export type Mat4 = [Vec4, Vec4, Vec4, Vec4];
/** 4×3 (`E`), rows. */
export type Mat43 = [Vec3, Vec3, Vec3, Vec3];

/** A JSON value (documents and scenes are JSON-serialisable data, contract §5.4.0). */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
