"""Fixed-point recovery decisions; actuator/vision adapters remain injectable."""

import time
import uuid

from control.arm import CommError
from control.fixed_sort import OBSERVATION_POSE, TargetRejected, select_target
from dataclasses import replace
from shared.schemas import BIN_BY_CLASS, Reason, SortEvent


class VerifiedGraspFailure(Exception):
    """Adapter verified an empty grasp, before any release or placement.

    Only raise when a retry is safe. BoardArm currently has no such sensor.
    Communication exceptions and unverified commands must never trigger retry.
    """


class FixedRunner:
    def __init__(self, detector, arm=None, sink=None, selector=select_target, placement_check=None):
        self.detector, self.arm, self.sink = detector, arm, sink
        self.selector = selector
        self.placement_check = placement_check
        self.halted = False

    def run_once(self, samples=5, min_confidence=.7, timeout_sec=2.0):
        if self.halted:
            raise CommError('通信或未知动作异常后禁止继续，请人工检查并重新启动')
        start = time.monotonic()
        result = {'command_sequence_completed': False, 'physical_success_confirmed': None, 'attempts': 0}
        cls, bin_id = '', 0
        reason = Reason.VISION_ERROR
        placement_confirmed = False
        try:
            target, observations = self.selector(self.detector, samples, min_confidence, timeout_sec=timeout_sec)
            result.update(detection=dict(target.__dict__), observations=observations)
            cls = target.cls
            if self.arm is None:
                result['status'] = 'dry_run'
                return result
            reason = Reason.COMM_ERROR
            if self.placement_check:
                self.placement_check.capture('before', target)
            action_start = time.monotonic()
            for attempt in range(2):
                result['attempts'] += 1
                try:
                    complete = self.arm.grasp(replace(target, u=320., v=240.))
                    if not complete:
                        # Existing driver has no reliable physical feedback.
                        raise RuntimeError('动作返回失败但未确认夹爪状态，停止且不自动重试')
                    break
                except VerifiedGraspFailure:
                    if attempt == 1:
                        self.arm.go_safe()
                        reason = Reason.GRASP_FAIL
                        result['status'] = 'skipped'
                        result['physical_success_confirmed'] = False
                        return result
            self.arm._move(OBSERVATION_POSE, 1800)
            result.update(command_sequence_completed=True, status='completed',
                          action_cost_ms=round((time.monotonic()-action_start)*1000))
            bin_id = BIN_BY_CLASS[cls]
            if self.placement_check:
                placement_confirmed = self.placement_check.capture('after', target)
            reason = Reason.OK if placement_confirmed else Reason.COMMAND_COMPLETE
            if placement_confirmed:
                result['physical_success_confirmed'] = True
            elif self.placement_check and self.placement_check.record.get('result') == 'placement_failed':
                result['physical_success_confirmed'] = False
                reason = Reason.PLACEMENT_FAILED
        except TargetRejected as exc:
            result.update(status='skipped', error=str(exc), observations=exc.observations)
            reason = exc.reason
        except KeyboardInterrupt:
            self.halted = self.arm is not None
            result.update(status='interrupted', error='用户中止，不再下发后续运动')
            reason = Reason.INTERRUPTED
        except Exception as exc:
            result.update(status='stopped', error=str(exc))
            self.halted = True
        finally:
            result['total_cost_ms'] = round((time.monotonic()-start)*1000)
            if self.arm is not None:
                event = SortEvent(uuid.uuid4().hex, time.time_ns()//1000000, cls,
                                  bin_id, placement_confirmed, result['total_cost_ms'], reason)
                result['event'] = event.to_dict()
                if self.sink:
                    self.sink.publish(event)
        return result
