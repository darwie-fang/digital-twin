# Passed to Isaac Sim with --exec: waits for the app to finish starting, then opens the room scene.
import asyncio, omni.usd, omni.kit.app

async def _go():
    app = omni.kit.app.get_app()
    for _ in range(120):
        await app.next_update_async()
    await omni.usd.get_context().open_stage_async("/workspace/room/room_twin.usda")
    print("ROOM LOADED")

asyncio.ensure_future(_go())
