try:
    from builtins import object
except ImportError:
    pass

import time
from threading import Thread
import logging

from transitions.extensions import MachineFactory
from transitions.extensions.nesting import NestedState
from .test_nesting import TestTransitions as TestsNested
from .test_core import TestTransitions as TestCore
from .utils import Stuff

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def heavy_processing():
    time.sleep(1)


def heavy_checking():
    time.sleep(1)
    return False


class TestLockedTransitions(TestCore):

    def setUp(self):
        self.stuff = Stuff(machine_cls=MachineFactory.get_predefined(locked=True))
        self.stuff.heavy_processing = heavy_processing
        self.stuff.machine.add_transition('forward', 'A', 'B', before='heavy_processing')

    def tearDown(self):
        pass

    def test_thread_access(self):
        thread = Thread(target=self.stuff.forward)
        thread.start()
        # give thread some time to start
        time.sleep(0.01)
        self.assertTrue(self.stuff.is_B())

    def test_parallel_access(self):
        thread = Thread(target=self.stuff.forward)
        thread.start()
        # give thread some time to start
        time.sleep(0.01)
        self.stuff.to_C()
        # if 'forward' has not been locked, it is still running
        # we have to wait to be sure it is done
        time.sleep(1)
        self.assertEqual(self.stuff.state, "C")

    def test_conditional_access(self):
        self.stuff.heavy_checking = heavy_checking  # checking takes 1s and returns False
        self.stuff.machine.add_transition('advance', 'A', 'B', conditions='heavy_checking')
        self.stuff.machine.add_transition('advance', 'A', 'D')
        t = Thread(target=self.stuff.advance)
        t.start()
        time.sleep(0.1)
        logger.info('Check if state transition done...')
        # Thread will release lock before Transition is finished
        self.assertTrue(self.stuff.is_D())

    def test_pickle(self):
        import sys
        if sys.version_info < (3, 4):
            import dill as pickle
        else:
            import pickle

        # go to non initial state B
        self.stuff.to_B()
        # pickle Stuff model
        dump = pickle.dumps(self.stuff)
        self.assertIsNotNone(dump)
        stuff2 = pickle.loads(dump)
        self.assertTrue(stuff2.is_B())
        # check if machines of stuff and stuff2 are truly separated
        stuff2.to_A()
        self.stuff.to_C()
        self.assertTrue(stuff2.is_A())
        thread = Thread(target=stuff2.forward)
        thread.start()
        # give thread some time to start
        time.sleep(0.01)
        # both objects should be in different states
        # and also not share locks
        begin = time.time()
        # stuff should not be locked and execute fast
        self.assertTrue(self.stuff.is_C())
        fast = time.time()
        # stuff2 should be locked and take about 1 second
        # to be executed
        self.assertTrue(stuff2.is_B())
        blocked = time.time()
        self.assertAlmostEqual(fast - begin, 0, delta=0.1)
        self.assertAlmostEqual(blocked - begin, 1, delta=0.1)


class TestMultipleContexts(TestCore):

    class DummyModel(object):
        pass

    class TestContext(object):
        def __init__(self, event_list):
            self._event_list = event_list

        def __enter__(self):
            self._event_list.append((self, "enter"))

        def __exit__(self, type, value, traceback):
            self._event_list.append((self, "exit"))

    def setUp(self):
        self.event_list = []

        self.s1 = self.DummyModel()

        self.c1 = self.TestContext(event_list=self.event_list)
        self.c2 = self.TestContext(event_list=self.event_list)
        self.c3 = self.TestContext(event_list=self.event_list)
        self.c4 = self.TestContext(event_list=self.event_list)

        self.stuff = Stuff(machine_cls=MachineFactory.get_predefined(locked=True), extra_kwargs={
            'machine_context': [self.c1, self.c2]
        })
        self.stuff.machine.add_model(self.s1, model_context=[self.c3, self.c4])
        del self.event_list[:]

        self.stuff.machine.add_transition('forward', 'A', 'B')

    def tearDown(self):
        self.stuff.machine.remove_model(self.s1)

    def test_ordering(self):
        self.stuff.forward()
        # There are a lot of internal enter/exits, but the key is that the outermost are in the expected order
        self.assertEqual((self.c1, "enter"), self.event_list[0])
        self.assertEqual((self.c2, "enter"), self.event_list[1])
        self.assertEqual((self.c2, "exit"), self.event_list[-2])
        self.assertEqual((self.c1, "exit"), self.event_list[-1])

    def test_model_context(self):
        self.s1.forward()
        self.assertEqual((self.c1, "enter"), self.event_list[0])
        self.assertEqual((self.c2, "enter"), self.event_list[1])

        # Since there are a lot of internal enter/exits, we don't actually know how deep in the stack
        # to look for these. Should be able to correct when https://github.com/tyarkoni/transitions/issues/167
        self.assertIn((self.c3, "enter"), self.event_list)
        self.assertIn((self.c4, "enter"), self.event_list)
        self.assertIn((self.c4, "exit"), self.event_list)
        self.assertIn((self.c3, "exit"), self.event_list)

        self.assertEqual((self.c2, "exit"), self.event_list[-2])
        self.assertEqual((self.c1, "exit"), self.event_list[-1])


# Same as TestLockedTransition but with LockedHierarchicalMachine
class TestLockedHierarchicalTransitions(TestsNested, TestLockedTransitions):
    def setUp(self):
        NestedState.separator = '_'
        states = ['A', 'B', {'name': 'C', 'children': ['1', '2', {'name': '3', 'children': ['a', 'b', 'c']}]},
                  'D', 'E', 'F']
        self.stuff = Stuff(states, machine_cls=MachineFactory.get_predefined(locked=True, nested=True))
        self.stuff.heavy_processing = heavy_processing
        self.stuff.machine.add_transition('forward', '*', 'B', before='heavy_processing')

    def test_parallel_access(self):
        thread = Thread(target=self.stuff.forward)
        thread.start()
        # give thread some time to start
        time.sleep(0.01)
        self.stuff.to_C()
        # if 'forward' has not been locked, it is still running
        # we have to wait to be sure it is done
        time.sleep(1)
        self.assertEqual(self.stuff.state, "C")

    def test_pickle(self):
        import sys
        if sys.version_info < (3, 4):
            import dill as pickle
        else:
            import pickle

        states = ['A', 'B', {'name': 'C', 'children': ['1', '2', {'name': '3', 'children': ['a', 'b', 'c']}]},
                  'D', 'E', 'F']
        transitions = [
            {'trigger': 'walk', 'source': 'A', 'dest': 'B'},
            {'trigger': 'run', 'source': 'B', 'dest': 'C'},
            {'trigger': 'sprint', 'source': 'C', 'dest': 'D'}
        ]
        m = self.stuff.machine_cls(states=states, transitions=transitions, initial='A')
        m.heavy_processing = heavy_processing
        m.add_transition('forward', 'A', 'B', before='heavy_processing')

        # # go to non initial state B
        m.to_B()

        # pickle Stuff model
        dump = pickle.dumps(m)
        self.assertIsNotNone(dump)
        m2 = pickle.loads(dump)
        self.assertTrue(m2.is_B())
        m2.to_C_3_a()
        m2.to_C_3_b()
        # check if machines of stuff and stuff2 are truly separated
        m2.to_A()
        m.to_C()
        self.assertTrue(m2.is_A())
        thread = Thread(target=m2.forward)
        thread.start()
        # give thread some time to start
        time.sleep(0.01)
        # both objects should be in different states
        # and also not share locks
        begin = time.time()
        # stuff should not be locked and execute fast
        self.assertTrue(m.is_C())
        fast = time.time()
        # stuff2 should be locked and take about 1 second
        # to be executed
        self.assertTrue(m2.is_B())
        blocked = time.time()
        self.assertAlmostEqual(fast - begin, 0, delta=0.1)
        self.assertAlmostEqual(blocked - begin, 1, delta=0.1)
