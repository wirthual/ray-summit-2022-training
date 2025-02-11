from gym.spaces import Dict, Discrete, MultiDiscrete
from ipywidgets import Output
from IPython import display
import numpy as np
import time

from ray.rllib.env.multi_agent_env import MultiAgentEnv


class MultiAgentArena(MultiAgentEnv):  # MultiAgentEnv is a gym.Env sub-class
    
    def __init__(self, config=None):
        super().__init__()
        
        # Create a default env config.        
        config = config or {}
        
        # Store the dimensions of the grid.
        self.width = config.get("width", 10)
        self.height = config.get("height", 10)

        # End an episode after this many timesteps (return done=True).
        self.timestep_limit = config.get("timestep_limit", 100)

        # Define our observation space (per-agent!).
        size = self.width * self.height
        self.observation_space = Dict({
            "agent1": MultiDiscrete([size, size]),
            "agent2": MultiDiscrete([size, size]),
        })
        # Define our action space (per-agent!).
        # 0=up, 1=right, 2=down, 3=left.
        self.action_space = Dict({
            "agent1": Discrete(4),
            "agent2": Discrete(4),
        })

        # Reset env.
        self.reset()

        # For rendering.
        self.out = None
        if config.get("render"):
            self.out = Output()
            display.display(self.out)

        # Define our agent IDs.
        self._agent_ids = {"agent1", "agent2"}        

    def reset(self):
        """Returns initial observation of new episode."""

        # Store each agents' current position as row-major coords.
        self.agent1_pos = [0, 0]  # upper left corner
        self.agent2_pos = [self.height - 1, self.width - 1]  # lower bottom corner

        # Reset agent1's visited fields (set of x/y-tuples).
        self.agent1_visited_fields = {tuple(self.agent1_pos)}

        # How many timesteps have we done in this episode.
        self.timesteps = 0

        # Did we have a collision in recent step?
        self.collision = False
        # How many collisions in total have we had in this episode?
        self.num_collisions = 0

        # Each agents' accumulated rewards in the this episode.
        self.agent1_R = 0.0
        self.agent2_R = 0.0

        # Return the initial observation in the new episode.
        return self._get_obs()

    def step(self, action: dict):
        """
        Returns (next observation, rewards, dones, infos) after having taken the given actions.
        
        e.g.
        `action={"agent1": action_for_agent1, "agent2": action_for_agent2}`
        """
        # Make sure, action dict is complete.
        assert "agent1" in action and "agent2" in action and len(action) == 2, "ERROR"        

        # Increase our time steps counter by 1.
        self.timesteps += 1
        # An episode is "done" when we reach the time step limit.
        is_done = self.timesteps >= self.timestep_limit

        # Agent2 always moves first.
        # events = [collision|agent1_new_field]
        events = self._move(self.agent2_pos, action["agent2"], is_agent1=False)
        events |= self._move(self.agent1_pos, action["agent1"], is_agent1=True)

        # Determine rewards based on the collected events:
        r1 = -1.0 if "collision" in events else 1.0 if "agent1_new_field" in events else -0.5
        r2 = 1.0 if "collision" in events else -0.1
        
        rewards = {
            "agent1": r1,
            "agent2": r2,
        }

        # Generate a `done` dict (per-agent and total).
        dones = {
            "agent1": is_done,
            "agent2": is_done,
            # special `__all__` key indicates that the episode is done for all agents.
            "__all__": is_done,
        }

        # Useful for rendering.
        self.agent1_R += r1
        self.agent2_R += r2
        self.collision = "collision" in events
        if self.collision is True:
            self.num_collisions += 1    

        return self._get_obs(), rewards, dones, {}  # <- info dict (not needed here).

    def _get_obs(self):
        """
        Returns obs dict (agent name to discrete-pos tuple) using each
        agent's current x/y-positions.
        """
        ag1_discrete_pos = self.agent1_pos[0] * self.width + \
            (self.agent1_pos[1] % self.width)
        ag2_discrete_pos = self.agent2_pos[0] * self.width + \
            (self.agent2_pos[1] % self.width)
        return {
            "agent1": np.array([ag1_discrete_pos, ag2_discrete_pos]),
            "agent2": np.array([ag2_discrete_pos, ag1_discrete_pos]),
        }

    def _move(self, coords, action, is_agent1):
        """
        Moves an agent (agent1 iff is_agent1=True, else agent2) from `coords` (x/y) using the
        given action (0=up, 1=right, etc..) and returns a resulting events dict:
        Agent1: "new" when entering a new field. "bumped" when having been bumped into by agent2.
        Agent2: "bumped" when bumping into agent1 (agent1 then gets -1.0).
        """
        orig_coords = coords[:]
        # Change the row: 0=up (-1), 2=down (+1)
        coords[0] += -1 if action == 0 else 1 if action == 2 else 0
        # Change the column: 1=right (+1), 3=left (-1)
        coords[1] += 1 if action == 1 else -1 if action == 3 else 0

        # Solve collisions.
        # Make sure, we don't end up on the other agent's position.
        # If yes, don't move (we are blocked).
        if (is_agent1 and coords == self.agent2_pos) or (not is_agent1 and coords == self.agent1_pos):
            coords[0], coords[1] = orig_coords
            # Agent2 blocked agent1 (agent1 tried to run into agent2)
            # OR Agent2 bumped into agent1 (agent2 tried to run into agent1)
            return {"collision"}

        # No agent blocking -> check walls.
        if coords[0] < 0:
            coords[0] = 0
        elif coords[0] >= self.height:
            coords[0] = self.height - 1
        if coords[1] < 0:
            coords[1] = 0
        elif coords[1] >= self.width:
            coords[1] = self.width - 1

        # If agent1 -> "agent1_new_field" if new tile covered.
        if is_agent1 and not tuple(coords) in self.agent1_visited_fields:
            self.agent1_visited_fields.add(tuple(coords))
            return {"agent1_new_field"}
        # No new tile for agent1.
        return set()

    def render(self, mode=None):

        if self.out is None:
            self.out = Output()
            display.display(self.out)
        if self.out is not None:
            self.out.clear_output(wait=True)

        print("_" * (self.width + 2))
        for r in range(self.height):
            print("|", end="")
            for c in range(self.width):
                if self.agent1_pos == [r, c]:
                    print("1", end="")
                elif self.agent2_pos == [r, c]:
                    print("2", end="")
                elif (r, c) in self.agent1_visited_fields:
                    print(".", end="")
                else:
                    print(" ", end="")
            print("|")
        print("‾" * (self.width + 2))
        print(f"{'!!Collision!!' if self.collision else ''}")
        print("R1={: .1f}".format(self.agent1_R))
        print("R2={: .1f} ({} collisions)".format(self.agent2_R, self.num_collisions))
        print("Agent1's x/y position={}".format(self.agent1_pos))
        print("Agent2's x/y position={}".format(self.agent2_pos))
        print("Env timesteps={}".format(self.timesteps))
        print()
        time.sleep(0.3)

        
def play_one_episode(*, env=None, algorithm=None):
    """Renders one episode using random actions of algorithm actions."""

    # Construct the environment object.
    if env is None:
        env = MultiAgentArena(config={"render": True})

    with env.out:

        # Call the env's `reset()` method to start a new episode.
        obs = env.reset()
        env.render()

        while True:
            # Compute actions separately for each agent.
            if algorithm is not None:
                actions = {
                    "agent1": algorithm.compute_single_action(obs["agent1"], policy_id="policy1"),
                    "agent2": algorithm.compute_single_action(obs["agent2"], policy_id="policy2"),
                }
            else:
                actions = env.action_space.sample()

            # Send the action-dict to the env, using the `step()` method.
            obs, rewards, dones, _ = env.step(actions)

            # Get a rendered image from the env.
            env.render()

            # If agent1 is done (feel free to check for agent2; they should be done at the same time) ...
            # -> break out of the loop.
            if dones["agent1"]:
                break
