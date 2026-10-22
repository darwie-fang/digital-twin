"""Convert a Scaniverse Gaussian-splat PLY into an Omniverse-ready USD stage (no pxr needed).

Outputs (in out_dir):
  apartment_twin.usda      root stage: lights, camera, physics scene, references the two layers
  splats_points.usda       UsdGeom.Points  - one point per splat, color + size + opacity
  collider_mesh.usda       UsdGeom.Mesh    - voxelized surface, vertex colors, PhysicsCollisionAPI
"""
import sys, os, numpy as np

ply, out_dir = sys.argv[1], sys.argv[2]
VOX = 0.04          # voxel size (m) for the collider mesh
SH_C0 = 0.28209479177387814
os.makedirs(out_dir, exist_ok=True)

# ---------- read ----------
with open(ply, 'rb') as f:
    props, n = [], 0
    while True:
        l = f.readline().strip()
        if l.startswith(b'element vertex'): n = int(l.split()[-1])
        if l.startswith(b'property'): props.append(l.split()[-1].decode())
        if l == b'end_header': break
    d = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
P = {p: i for i, p in enumerate(props)}
xyz = d[:, [P['x'], P['y'], P['z']]].astype(np.float64)
rgb = np.clip(0.5 + SH_C0 * d[:, [P['f_dc_0'], P['f_dc_1'], P['f_dc_2']]], 0, 1)
op = 1 / (1 + np.exp(-d[:, P['opacity']]))
scale = np.exp(d[:, [P['scale_0'], P['scale_1'], P['scale_2']]])

# ---------- clean + orient (Y-up, metres, floor at y=0, centred) ----------
r = np.linalg.norm(xyz - np.median(xyz, 0), axis=1)
keep = (r < 8) & (op > 0.08) & (scale.max(1) < 0.5)
xyz, rgb, op, scale = xyz[keep], rgb[keep], op[keep], scale[keep]
solid = (op > 0.5) & (scale.max(1) < 0.1)
floor_y = np.percentile(xyz[solid, 1], 1)
cx, cz = np.median(xyz[solid, 0]), np.median(xyz[solid, 2])
xyz -= [cx, floor_y, cz]
print(f'{n} splats in, {keep.sum()} kept; floor at y={floor_y:.2f}')

def arr(a, fmt):
    return '[' + ', '.join(fmt % tuple(v) if np.ndim(v) else fmt % v for v in a) + ']'

# ---------- layer 1: points ----------
width = np.clip(2 * np.sqrt(np.prod(np.sort(scale, 1)[:, 1:], 1)), 0.003, 0.08)  # mean of 2 largest axes
lo, hi = xyz.min(0), xyz.max(0)
with open(f'{out_dir}/splats_points.usda', 'w') as f:
    f.write(f'''#usda 1.0
(
    defaultPrim = "Splats"
    metersPerUnit = 1
    upAxis = "Y"
)

def Points "Splats" (
    prepend apiSchemas = ["MaterialBindingAPI"]
)
{{
    float3[] extent = [({lo[0]:.3f}, {lo[1]:.3f}, {lo[2]:.3f}), ({hi[0]:.3f}, {hi[1]:.3f}, {hi[2]:.3f})]
    point3f[] points = {arr(xyz, '(%.4f, %.4f, %.4f)')}
    float[] widths = {arr(width, '%.4f')} (interpolation = "vertex")
    color3f[] primvars:displayColor = {arr(rgb, '(%.3f, %.3f, %.3f)')} (interpolation = "vertex")
    float[] primvars:displayOpacity = {arr(op, '%.3f')} (interpolation = "vertex")
    rel material:binding = </Splats/VertexColorMat>

    def Material "VertexColorMat"
    {{
        token outputs:surface.connect = </Splats/VertexColorMat/PBR.outputs:surface>
        def Shader "PBR"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </Splats/VertexColorMat/ColorReader.outputs:result>
            float inputs:roughness = 0.9
            token outputs:surface
        }}
        def Shader "ColorReader"
        {{
            uniform token info:id = "UsdPrimvarReader_float3"
            string inputs:varname = "displayColor"
            float3 outputs:result
        }}
    }}
}}
''')

# ---------- layer 2: voxel collider mesh ----------
vx = np.floor(xyz[solid] / VOX).astype(np.int64)
keys, inv, cnt = np.unique(vx, axis=0, return_inverse=True, return_counts=True)
inv = inv.ravel()
col = np.zeros((len(keys), 3)); np.add.at(col, inv, rgb[solid]); col /= cnt[:, None]
m = cnt >= 2
keys, col = keys[m], col[m]
occ = {tuple(k) for k in keys}
# faces: (normal offset, 4 corner offsets CCW seen from outside)
FACES = [((1,0,0), [(1,0,0),(1,1,0),(1,1,1),(1,0,1)]), ((-1,0,0), [(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
         ((0,1,0), [(0,1,0),(0,1,1),(1,1,1),(1,1,0)]), ((0,-1,0), [(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
         ((0,0,1), [(0,0,1),(1,0,1),(1,1,1),(0,1,1)]), ((0,0,-1), [(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]
vid, verts, fidx, fcol = {}, [], [], []
for k, c in zip(map(tuple, keys), col):
    for nrm, corners in FACES:
        if (k[0]+nrm[0], k[1]+nrm[1], k[2]+nrm[2]) in occ: continue
        for o in corners:
            v = (k[0]+o[0], k[1]+o[1], k[2]+o[2])
            if v not in vid: vid[v] = len(verts); verts.append(v)
            fidx.append(vid[v])
        fcol.append(c)
verts = np.array(verts, float) * VOX
nf = len(fcol)
print(f'collider: {len(keys)} voxels -> {nf} quads, {len(verts)} verts')
with open(f'{out_dir}/collider_mesh.usda', 'w') as f:
    f.write(f'''#usda 1.0
(
    defaultPrim = "Collider"
    metersPerUnit = 1
    upAxis = "Y"
)

def Mesh "Collider" (
    prepend apiSchemas = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI"]
)
{{
    uniform token physics:approximation = "none"
    uniform token subdivisionScheme = "none"
    int[] faceVertexCounts = {arr([4]*nf, '%d')}
    int[] faceVertexIndices = {arr(fidx, '%d')}
    point3f[] points = {arr(verts, '(%.3f, %.3f, %.3f)')}
    color3f[] primvars:displayColor = {arr(fcol, '(%.3f, %.3f, %.3f)')} (interpolation = "uniform")
}}
''')

# ---------- root stage ----------
ex = xyz[solid]; c = (np.percentile(ex, 5, 0) + np.percentile(ex, 95, 0)) / 2
span = np.percentile(ex, 95, 0) - np.percentile(ex, 5, 0)
cam = c + np.array([span[0] * 0.9, span[1] * 0.9 + 1.0, span[2] * 1.1])
with open(f'{out_dir}/apartment_twin.usda', 'w') as f:
    f.write(f'''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
    doc = "Digital twin of an apartment, built from a Scaniverse Gaussian-splat scan (Manhattan.ply)."
)

def Xform "World"
{{
    def PhysicsScene "PhysicsScene"
    {{
        vector3f physics:gravityDirection = (0, -1, 0)
        float physics:gravityMagnitude = 9.81
    }}

    def Xform "Apartment"
    {{
        def "Splats" (
            prepend references = @./splats_points.usda@
        )
        {{
        }}

        def "Collider" (
            prepend references = @./collider_mesh.usda@
        )
        {{
            token visibility = "invisible"
        }}
    }}

    def Mesh "GroundPlane" (
        prepend apiSchemas = ["PhysicsCollisionAPI"]
    )
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(-10, -0.01, -10), (-10, -0.01, 10), (10, -0.01, 10), (10, -0.01, -10)]
        color3f[] primvars:displayColor = [(0.35, 0.35, 0.37)]
    }}

    def Xform "TestBox" (
        doc = "A 20 cm box dropped from 1.5 m to show physics hitting the scanned geometry."
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {{
        float physics:mass = 1
        double3 xformOp:translate = ({c[0]:.2f}, 1.5, {c[2]:.2f})
        uniform token[] xformOpOrder = ["xformOp:translate"]
        def Cube "Geom" (
            prepend apiSchemas = ["PhysicsCollisionAPI"]
        )
        {{
            double size = 0.2
            color3f[] primvars:displayColor = [(0.46, 0.73, 0.0)]
        }}
    }}

    def DomeLight "Sky"
    {{
        float inputs:intensity = 800
    }}

    def DistantLight "Sun"
    {{
        float inputs:intensity = 2500
        float inputs:angle = 1
        float3 xformOp:rotateXYZ = (-55, 35, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }}

    def Camera "OverviewCam"
    {{
        float focalLength = 18
        double3 xformOp:translate = ({cam[0]:.2f}, {cam[1]:.2f}, {cam[2]:.2f})
        float3 xformOp:rotateXYZ = (-30, 40, 0)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
    }}
}}
''')
np.savez_compressed(f'{out_dir}/_preview.npz', xyz=xyz[op > 0.25].astype(np.float32), rgb=rgb[op > 0.25].astype(np.float32))
print('done')
