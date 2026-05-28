#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .point import Point
import numpy as np
from math import sqrt,pi 


class PathManager:
    def __init__(self, path, is_closed_path, local_path_size):
        self.path = path
        self.is_closed_path = is_closed_path
        self.local_path_size = local_path_size
        self.velocity_profile = []
        self._last_wp = 0   # 마지막으로 찾은 웨이포인트 인덱스 캐시

    def set_velocity_profile(self, max_velocity, road_friction, window_size):
        # TODO: moving window를 설정하는 방식 개선.
        max_velocity = max_velocity / 3.6
        velocity_profile = []
        for i in range(0, window_size):
            velocity_profile.append(max_velocity)

        target_velocity = max_velocity

        for i in range(window_size, len(self.path)-window_size):
            x_list = []
            y_list = []
            for window in range(-window_size, window_size):
                x = self.path[i+window].x
                y = self.path[i+window].y
                x_list.append(x)
                y_list.append(y)

            x_start  = x_list[0]
            x_end    = x_list[-1]
            x_mid    = x_list[int(len(x_list)/2)]

            y_start  = y_list[0]
            y_end    = y_list[-1]
            y_mid    = y_list[int(len(y_list)/2)]

            dSt = np.array([x_start - x_mid, y_start - y_mid])
            dEd = np.array([x_end - x_mid, y_end - y_mid])

            Dcom = 2 * (dSt[0]*dEd[1] - dSt[1]*dEd[0])

            dSt2 = np.dot(dSt,dSt)
            dEd2 = np.dot(dEd,dEd)

            U1 = (dEd[1] * dSt2 - dSt[1] * dEd2)/Dcom
            U2 = (dSt[0] * dEd2 - dEd[0] * dSt2)/Dcom

            tmp_r = sqrt(pow(U1, 2)+ pow(U2, 2))

            if np.isnan(tmp_r):
                tmp_r = float('inf')

            target_velocity = sqrt(tmp_r*9.8*road_friction)

            if target_velocity > max_velocity:
                target_velocity = max_velocity

            velocity_profile.append(target_velocity)

        for i in range(len(self.path)-window_size, len(self.path) - 10):
            velocity_profile.append(max_velocity)

        for i in range(len(self.path) - 10, len(self.path)):
            # 순환 경로(closed path)는 끝 지점에서도 속도를 유지해야 함.
            # 열린 경로(open path)만 마지막 10개 웨이포인트를 0으로 감속.
            velocity_profile.append(0. if not self.is_closed_path else max_velocity)

        self.velocity_profile = velocity_profile

    def get_local_path(self, vehicle_state):
        n = len(self.path)
        # 이전 인덱스 ±window 범위만 탐색 (closed path는 모듈로 처리)
        BACK, FRONT = 5, 100
        min_distance = float('inf')
        current_waypoint = self._last_wp

        for offset in range(-BACK, FRONT + 1):
            if self.is_closed_path:
                i = (self._last_wp + offset) % n
            else:
                i = self._last_wp + offset
                if i < 0 or i >= n:
                    continue
            dx = self.path[i].x - vehicle_state.position.x
            dy = self.path[i].y - vehicle_state.position.y
            d  = dx * dx + dy * dy
            if d < min_distance:
                min_distance = d
                current_waypoint = i

        self._last_wp = current_waypoint

        if current_waypoint + self.local_path_size < len(self.path):
            local_path = self.path[current_waypoint:current_waypoint + self.local_path_size]
        else:
            local_path = self.path[current_waypoint:]
            # 연결된 경로 (closed path) 일 경우, 경로 끝과 처음을 이어준다.
            if self.is_closed_path:
                local_path += self.path[:self.local_path_size + len(self.path) - current_waypoint]

        return local_path, self.velocity_profile[current_waypoint]