"""
Generic Finite State Machine
Used for OSPF neighbor state machine and other stateful components
"""

import logging
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)


class StateMachine:
    """
    Generic Finite State Machine with transitions and callbacks
    """

    def __init__(self, initial_state: Any, name: str = "FSM"):
        """
        Initialize state machine

        Args:
            initial_state: Initial state
            name: Name for logging purposes
        """
        self.state = initial_state
        self.name = name
        self.transitions: Dict[Any, Dict[str, Any]] = {}
        self.on_enter_callbacks: Dict[Any, list] = {}
        self.on_exit_callbacks: Dict[Any, list] = {}
        self.state_names: Dict[Any, str] = {}

        logger.debug(f"{self.name}: Initial state = {initial_state}")

    def add_transition(self, from_state: Any, event: str, to_state: Any):
        """
        Add state transition

        Args:
            from_state: Source state
            event: Event name that triggers transition
            to_state: Destination state
        """
        if from_state not in self.transitions:
            self.transitions[from_state] = {}

        self.transitions[from_state][event] = to_state
        logger.debug(f"{self.name}: Added transition {from_state} --[{event}]--> {to_state}")

    def add_on_enter(self, state: Any, callback: Callable):
        """
        Add callback to execute when entering state

        Args:
            state: State to attach callback to
            callback: Callable to execute on entry
        """
        if state not in self.on_enter_callbacks:
            self.on_enter_callbacks[state] = []

        self.on_enter_callbacks[state].append(callback)

    def add_on_exit(self, state: Any, callback: Callable):
        """
        Add callback to execute when exiting state

        Args:
            state: State to attach callback to
            callback: Callable to execute on exit
        """
        if state not in self.on_exit_callbacks:
            self.on_exit_callbacks[state] = []

        self.on_exit_callbacks[state].append(callback)

    def set_state_name(self, state: Any, name: str):
        """
        Set human-readable name for state

        Args:
            state: State value
            name: Human-readable name
        """
        self.state_names[state] = name

    def get_state_name(self, state: Optional[Any] = None) -> str:
        """
        Get human-readable name for state

        Args:
            state: State to get name for (None = current state)

        Returns:
            State name or string representation
        """
        if state is None:
            state = self.state

        return self.state_names.get(state, str(state))

    def trigger(self, event: str, **kwargs) -> bool:
        """
        Trigger event and potentially transition to new state

        Args:
            event: Event name
            **kwargs: Additional arguments passed to callbacks

        Returns:
            True if transition occurred, False otherwise
        """
        # Check if transition exists for current state and event
        if self.state not in self.transitions:
            logger.debug(f"{self.name}: No transitions from state {self.get_state_name()}")
            return False

        if event not in self.transitions[self.state]:
            logger.debug(f"{self.name}: No transition for event '{event}' in state {self.get_state_name()}")
            return False

        # Get new state
        old_state = self.state
        new_state = self.transitions[self.state][event]

        # Execute exit callbacks
        if old_state in self.on_exit_callbacks:
            for callback in self.on_exit_callbacks[old_state]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    logger.error(f"{self.name}: Exit callback error in state {self.get_state_name(old_state)}: {e}")

        # Transition
        self.state = new_state

        # Log transition
        logger.info(f"{self.name}: {self.get_state_name(old_state)} --[{event}]--> {self.get_state_name(new_state)}")

        # Execute enter callbacks
        if new_state in self.on_enter_callbacks:
            for callback in self.on_enter_callbacks[new_state]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    logger.error(f"{self.name}: Enter callback error in state {self.get_state_name(new_state)}: {e}")

        return True

    def can_transition(self, event: str) -> bool:
        """
        Check if event can trigger transition from current state

        Args:
            event: Event name

        Returns:
            True if transition is possible
        """
        return (self.state in self.transitions and
                event in self.transitions[self.state])

    def get_valid_events(self) -> Set[str]:
        """
        Get valid events for current state

        Returns:
            Set of valid event names
        """
        if self.state not in self.transitions:
            return set()

        return set(self.transitions[self.state].keys())

    def reset(self, new_state: Any):
        """
        Reset state machine to new state without callbacks

        Args:
            new_state: New state to set
        """
        old_state = self.state
        self.state = new_state
        logger.info(f"{self.name}: Reset from {self.get_state_name(old_state)} to {self.get_state_name(new_state)}")

    def get_state(self) -> Any:
        """
        Get current state

        Returns:
            Current state
        """
        return self.state

    def __repr__(self) -> str:
        return f"StateMachine(name={self.name}, state={self.get_state_name()})"
