import sys, os, glob, shutil
from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, Gf, Sdf, Vt

src = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob('/workspace/*.usdz'))[-1]
outdir = '/workspace/room'
os.makedirs(outdir, exist_ok=True)
shutil.copy(src, f'{outdir}/scan.usdz')
s = Usd.Stage.Open(f'{outdir}/scan.usdz')
up, mpu = UsdGeom.GetStageUpAxis(s), UsdGeom.GetStageMetersPerUnit(s)
dp = s.GetDefaultPrim() or next(iter(s.GetPseudoRoot().GetChildren()))
meshes = [p for p in s.Traverse() if p.IsA(UsdGeom.Mesh)]
bb = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default', 'render']).ComputeWorldBound(dp).ComputeAlignedRange()
mn, mx = bb.GetMin(), bb.GetMax()
nf = sum(len(UsdGeom.Mesh(m).GetFaceVertexCountsAttr().Get() or []) for m in meshes)
print(f'upAxis={up} metersPerUnit={mpu} defaultPrim={dp.GetPath()} meshes={len(meshes)} faces={nf}')
print(f'bbox min={mn} max={mx}')

if up == 'Z':   # (x,y,z) -> (x,z,-y)
    lo = Gf.Vec3d(mn[0], mn[2], -mx[1]) * mpu; hi = Gf.Vec3d(mx[0], mx[2], -mn[1]) * mpu; rotx = -90.0
else:
    lo = Gf.Vec3d(mn) * mpu; hi = Gf.Vec3d(mx) * mpu; rotx = 0.0
c = (lo + hi) / 2; size = hi - lo
print(f'room size (m, x/height/z) = {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}')

st = Usd.Stage.CreateNew(f'{outdir}/room_twin.usda')
UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.y); UsdGeom.SetStageMetersPerUnit(st, 1.0)
world = UsdGeom.Xform.Define(st, '/World'); st.SetDefaultPrim(world.GetPrim())
ps = UsdPhysics.Scene.Define(st, '/World/PhysicsScene')
ps.CreateGravityDirectionAttr(Gf.Vec3f(0, -1, 0)); ps.CreateGravityMagnitudeAttr(9.81)

room = UsdGeom.Xform.Define(st, '/World/Room')
room.GetPrim().GetReferences().AddReference('./scan.usdz', dp.GetPath())
room.AddTranslateOp().Set(Gf.Vec3d(-c[0], -lo[1], -c[2]))
room.AddRotateXOp().Set(rotx)
room.AddScaleOp().Set(Gf.Vec3f(mpu, mpu, mpu))
n = 0
for p in st.Traverse():
    if p.IsA(UsdGeom.Mesh):
        UsdPhysics.CollisionAPI.Apply(p)
        UsdPhysics.MeshCollisionAPI.Apply(p).CreateApproximationAttr('none')
        n += 1
print(f'collision applied to {n} meshes')

g = UsdGeom.Mesh.Define(st, '/World/SafetyFloor')
g.CreatePointsAttr([(-20, -0.05, -20), (-20, -0.05, 20), (20, -0.05, 20), (20, -0.05, -20)])
g.CreateFaceVertexCountsAttr([4]); g.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
g.CreateDisplayColorAttr([(0.3, 0.3, 0.32)]); g.CreateVisibilityAttr('invisible')
UsdPhysics.CollisionAPI.Apply(g.GetPrim())

drop_h = min(size[1] * 0.8, 1.8)
cols = [(0.46, 0.73, 0.0), (0.95, 0.55, 0.1), (0.2, 0.55, 0.95), (0.9, 0.2, 0.3), (0.95, 0.85, 0.2)]
for i, (dx, dz) in enumerate([(0, 0), (0.35, 0.2), (-0.3, 0.3), (0.25, -0.35), (-0.35, -0.25)]):
    b = UsdGeom.Xform.Define(st, f'/World/TestBoxes/Box{i}')
    b.AddTranslateOp().Set(Gf.Vec3d(dx * size[0] * 0.5, drop_h + 0.25 * i, dz * size[2] * 0.5))
    UsdPhysics.RigidBodyAPI.Apply(b.GetPrim()); UsdPhysics.MassAPI.Apply(b.GetPrim()).CreateMassAttr(1.0)
    cube = UsdGeom.Cube.Define(st, f'/World/TestBoxes/Box{i}/Geom')
    cube.CreateSizeAttr(0.15); cube.CreateDisplayColorAttr([cols[i]])
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())

UsdLux.DomeLight.Define(st, '/World/Sky').CreateIntensityAttr(1000)
sun = UsdLux.DistantLight.Define(st, '/World/Sun'); sun.CreateIntensityAttr(2000); sun.CreateAngleAttr(1.0)
sun.AddRotateXYZOp().Set(Gf.Vec3f(-55, 35, 0))
cam = UsdGeom.Camera.Define(st, '/World/OverviewCam'); cam.CreateFocalLengthAttr(16)
cam.AddTranslateOp().Set(Gf.Vec3d(size[0] * 0.45, size[1] * 0.9, size[2] * 0.45))
cam.AddRotateXYZOp().Set(Gf.Vec3f(-35, 45, 0))
st.GetRootLayer().Save()

with open(f'{outdir}/open_room.py', 'w') as f:
    f.write('import asyncio, omni.usd, omni.kit.app\n'
            'async def _go():\n'
            '    app = omni.kit.app.get_app()\n'
            '    for _ in range(120):\n'
            '        await app.next_update_async()\n'
            f'    await omni.usd.get_context().open_stage_async("{outdir}/room_twin.usda")\n'
            '    print("ROOM LOADED")\n'
            'asyncio.ensure_future(_go())\n')
print('BUILD OK ->', f'{outdir}/room_twin.usda')
