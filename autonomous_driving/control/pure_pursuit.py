#!/usr/bin/env python
# -*- coding: utf-8 -*-
from ..vehicle_state import VehicleState
import numpy as np


class PurePursuit(object):
    def __init__(self, lfd_gain, wheelbase, min_lfd, max_lfd):
        """Pure Pursuit 알고리즘을 이용한 Steering 계산"""
        self.lfd_gain = lfd_gain
        self.wheelbase = wheelbase
        self.min_lfd = min_lfd
        self.max_lfd = max_lfd

        self._path = []
        self._vehicle_state = VehicleState()
        self._last_lfd_idx = 0

    @property
    def path(self):
        return self._path

    @property
    def vehicle_state(self):
        return self._vehicle_state

    @path.setter
    def path(self, path):
        self._path = path
        self._last_lfd_idx = 0

    @vehicle_state.setter
    def vehicle_state(self, vehicle_state):
        self._vehicle_state = vehicle_state

    def calculate_steering_angle(self):
        lfd = self.lfd_gain * self._vehicle_state.velocity
        lfd = np.clip(lfd, self.min_lfd, self.max_lfd)

        steering_angle = 0.
        n = len(self._path)
        # 마지막 lookahead 인덱스부터 탐색, 없으면 처음부터 재탐색
        for attempt in range(2):
            start = self._last_lfd_idx if attempt == 0 else 0
            for i in range(start, n):
                diff = self._path[i] - self._vehicle_state.position
                rotated_diff = diff.rotate(-self._vehicle_state.yaw)
                if rotated_diff.x > 0:
                    dis = rotated_diff.distance()
                    if dis >= lfd:
                        theta = rotated_diff.angle
                        steering_angle = np.arctan2(2 * self.wheelbase * np.sin(theta), lfd)
                        self._last_lfd_idx = i
                        return steering_angle
        return steering_angle
