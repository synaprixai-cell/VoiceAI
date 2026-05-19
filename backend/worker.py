"""LiveKit agent worker entrypoint — runs as separate Railway service."""
from livekit.agents import WorkerOptions, cli
from agent.maya_agent import entrypoint, prewarm

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
