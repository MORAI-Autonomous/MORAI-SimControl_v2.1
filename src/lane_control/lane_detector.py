# lane_detector.py
# Sliding Window 차선 검출: 히스토그램 기준점 → 폴리핏 → 오프셋/곡률 계산

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple
from lane_control.lane_preprocessor import LanePreprocessor, BEVParams


# BEV 픽셀 → 미터 변환 (★ BEVParams.dst_margin 변경 시 BEV_DST_MARGIN 도 수정 ★)
BEV_DST_MARGIN = 120        # BEVParams.dst_margin 과 일치
ROAD_WIDTH_M   = 8.0        # BEV 가시 가로 실거리 (m)
BEV_IMG_W      = 640

YM_PER_PIX = 15.0 / 480    # 전방 약 15m → 480px
XM_PER_PIX = ROAD_WIDTH_M / (BEV_IMG_W - 2 * BEV_DST_MARGIN)  # ≈ 0.020 m/px


# ─── 검출 결과 ────────────────────────────────────────────────────
@dataclass
class LaneResult:
    # 다항식 계수 [A, B, C]  (x = Ay² + By + C)
    left_fit:  Optional[np.ndarray] = None
    right_fit: Optional[np.ndarray] = None

    # 차선 중앙 오프셋 (미터, + → 차량이 중앙 기준 좌측)
    offset_m: float = 0.0

    # 곡률 반경 (미터, 클수록 직선)
    curve_radius_m: float = 9999.0

    # 검출 신뢰도
    left_detected:  bool = False
    right_detected: bool = False

    # 시각화 이미지 (BEV 위에 차선/윈도우 표시)
    viz: Optional[np.ndarray] = None


# ─── LaneDetector ────────────────────────────────────────────────
class LaneDetector:
    """
    Parameters
    ----------
    n_windows  : 슬라이딩 윈도우 개수 (기본 9)
    margin     : 윈도우 좌우 폭 (픽셀, 기본 60)
    min_pixels : 윈도우 내 최소 픽셀 수 (재중심 기준, 기본 30)
    img_w, img_h : BEV 이미지 크기
    """

    def __init__(
        self,
        n_windows:     int   = 9,
        margin:        int   = 80,    # 점선 차선 대응: 넓은 탐색 범위
        min_pixels:    int   = 15,    # 점선 차선 대응: 낮은 최소 픽셀
        img_w:         int   = 640,
        img_h:         int   = 480,
        search_ratio:  float = 0.65,  # 히스토그램 탐색 하단 비율
        dst_margin:    int   = BEV_DST_MARGIN,
        hist_bot_crop: int   = 80,    # 카메라 근접 배리어 오염 방지: 하단 N행 제외
    ):
        self.n_windows    = n_windows
        self.margin       = margin
        self.min_pixels   = min_pixels
        self.img_w        = img_w
        self.img_h        = img_h
        self.search_ratio = search_ratio
        self._hmask_l     = dst_margin
        self._hmask_r     = img_w - dst_margin
        self._hist_bot_crop = hist_bot_crop
        self._prev_left:  Optional[np.ndarray] = None
        self._prev_right: Optional[np.ndarray] = None
        self._left_miss_cnt:  int = 0
        self._right_miss_cnt: int = 0

    # ── 공개 API ─────────────────────────────────────────────────
    def detect(self, binary: np.ndarray) -> LaneResult:
        """
        binary : BEV 이진화 이미지 (np.uint8, 단채널)
        반환   : LaneResult
        """
        if self._prev_left is None or self._prev_right is None:
            # 처음 or 놓친 후 → 전체 히스토그램 탐색
            result = self._sliding_window(binary)
        else:
            # 이전 결과 기반 빠른 탐색
            result = self._search_around_poly(binary)

        if self._needs_sparse_recovery(result):
            recovered = self._sparse_line_recovery(binary, result.viz)
            if recovered is not None:
                return recovered
        return result

    def reset(self):
        self._prev_left      = None
        self._prev_right     = None
        self._left_miss_cnt  = 0
        self._right_miss_cnt = 0

    # ── 차선 폭 기반 베이스 포인트 선택 ─────────────────────────
    @staticmethod
    def _find_best_base(histogram: np.ndarray, w: int):
        """히스토그램 좌우 피크 중 차선 폭(2~6m) 조건을 만족하는 중앙에 가장 가까운 쌍 선택.
        조건 만족 쌍 없으면 argmax 폴백."""
        LANE_W_MIN = int(2.0 / XM_PER_PIX)
        LANE_W_MAX = int(6.0 / XM_PER_PIX)
        MIN_PEAK_H = max(histogram.max() * 0.15, 5)

        def _peaks(arr, offset=0):
            cands = []
            for i in range(1, len(arr) - 1):
                if arr[i] >= MIN_PEAK_H and arr[i] >= arr[i-1] and arr[i] >= arr[i+1]:
                    cands.append(i + offset)
            return cands if cands else [int(np.argmax(arr)) + offset]

        mid = w // 2
        left_cands  = _peaks(histogram[:mid], offset=0)
        right_cands = _peaks(histogram[mid:], offset=mid)

        best_pair, best_score = None, -1e9
        for lc in left_cands:
            for rc in right_cands:
                lane_w = rc - lc
                if LANE_W_MIN <= lane_w <= LANE_W_MAX:
                    lane_w_m = lane_w * XM_PER_PIX
                    center = (lc + rc) * 0.5
                    left_strength = float(histogram[int(lc)])
                    right_strength = float(histogram[int(rc)])
                    score = left_strength + right_strength
                    score -= abs(lane_w_m - 3.5) * 80.0
                    score -= abs(center - mid) * 0.35
                    if lc < mid < rc:
                        score += 80.0
                    if score > best_score:
                        best_score, best_pair = score, (lc, rc)
        if best_pair:
            return best_pair
        return int(np.argmax(histogram[:mid])), int(np.argmax(histogram[mid:])) + mid

    # ── Sliding Window ───────────────────────────────────────────
    def _sliding_window(self, binary: np.ndarray) -> LaneResult:
        h, w  = binary.shape
        win_h = h // self.n_windows

        # 히스토그램: 상단 노이즈 + 하단 배리어 제외, 유효 도로 범위만 사용
        top_row = int(h * (1.0 - self.search_ratio))
        bot_row = max(h - self._hist_bot_crop, top_row + 1)
        histogram = np.sum(binary[top_row:bot_row, :], axis=0).astype(np.float32)
        histogram[:self._hmask_l] = 0
        histogram[self._hmask_r:] = 0

        # 신호 강도 체크: 너무 약한 쪽은 건너뜀 → single_lane_fallback 위임
        global_max  = float(histogram.max())
        _side_min   = max(global_max * 0.05, 2.0)
        _mid        = self.img_w // 2
        run_left    = float(histogram[:_mid].max()) >= _side_min
        run_right   = float(histogram[_mid:].max()) >= _side_min

        left_base, right_base = self._find_best_base(histogram, w)

        nonzero   = binary.nonzero()
        nz_y      = np.array(nonzero[0])
        nz_x      = np.array(nonzero[1])
        left_cur  = left_base
        right_cur = right_base

        left_inds_list  = []
        right_inds_list = []
        viz = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

        for i in range(self.n_windows):
            y_low  = h - (i + 1) * win_h
            y_high = h - i * win_h

            xl_lo, xl_hi = left_cur  - self.margin, left_cur  + self.margin
            xr_lo, xr_hi = right_cur - self.margin, right_cur + self.margin

            cv2.rectangle(viz, (xl_lo, y_low), (xl_hi, y_high), (0, 255, 0), 2)
            cv2.rectangle(viz, (xr_lo, y_low), (xr_hi, y_high), (0, 255, 0), 2)

            if run_left:
                good_l = np.where(
                    (nz_y >= y_low) & (nz_y < y_high) &
                    (nz_x >= xl_lo) & (nz_x < xl_hi)
                )[0]
                left_inds_list.append(good_l)
                if len(good_l) >= self.min_pixels:
                    left_cur = int(np.mean(nz_x[good_l]))

            if run_right:
                good_r = np.where(
                    (nz_y >= y_low) & (nz_y < y_high) &
                    (nz_x >= xr_lo) & (nz_x < xr_hi)
                )[0]
                right_inds_list.append(good_r)
                if len(good_r) >= self.min_pixels:
                    right_cur = int(np.mean(nz_x[good_r]))

        left_inds  = (np.concatenate(left_inds_list)  if left_inds_list
                      else np.array([], dtype=np.intp))
        right_inds = (np.concatenate(right_inds_list) if right_inds_list
                      else np.array([], dtype=np.intp))
        return self._fit_and_result(binary, nz_x, nz_y, left_inds, right_inds, viz)

    # ── 이전 다항식 주변 탐색 ────────────────────────────────────
    def _search_around_poly(self, binary: np.ndarray) -> LaneResult:
        nz   = binary.nonzero()
        nz_y = np.array(nz[0])
        nz_x = np.array(nz[1])
        m    = self.margin

        lf = self._prev_left
        rf = self._prev_right

        left_x_pred  = lf[0] * nz_y**2 + lf[1] * nz_y + lf[2]
        right_x_pred = rf[0] * nz_y**2 + rf[1] * nz_y + rf[2]

        left_inds  = np.where(np.abs(nz_x - left_x_pred)  < m)[0]
        right_inds = np.where(np.abs(nz_x - right_x_pred) < m)[0]

        viz = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        return self._fit_and_result(binary, nz_x, nz_y, left_inds, right_inds, viz)

    # ── 피팅 및 결과 계산 ────────────────────────────────────────
    def _fit_and_result(
        self,
        binary: np.ndarray,
        nz_x:   np.ndarray,
        nz_y:   np.ndarray,
        l_inds: np.ndarray,
        r_inds: np.ndarray,
        viz:    np.ndarray,
    ) -> LaneResult:
        h, w = binary.shape
        result = LaneResult()

        lx, ly = nz_x[l_inds], nz_y[l_inds]
        rx, ry = nz_x[r_inds], nz_y[r_inds]

        # 좌 다항식: 픽셀 5~79개 → 1차, 80+개 → 2차 (점선에서 wild fit 방지)
        _CACHE_MAX_MISS = 8   # 연속 미검출 허용 프레임 (0.4s @ 20Hz)
        if len(lx) >= 5:
            degree = 2 if len(lx) >= 80 else 1
            fit = np.polyfit(ly, lx, degree)
            fit = fit if degree == 2 else np.array([0.0, fit[0], fit[1]])
            if self._is_fit_sane(fit, h) and self._has_lane_support(lx, ly, h):
                result.left_fit      = fit
                result.left_detected = True
                self._prev_left      = fit
                self._left_miss_cnt  = 0          # 검출 성공 → 카운터 리셋
                viz[ly, lx] = (255, 50, 50)
            else:
                # 비정상 폴리핏 → 미검출 처리
                cv2.putText(viz, "L-FIT ERR", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 2)
                result.left_fit  = self._prev_left
                self._left_miss_cnt += 1
                if self._left_miss_cnt > _CACHE_MAX_MISS:
                    self._prev_left     = None
                    self._left_miss_cnt = 0
        else:
            result.left_fit  = self._prev_left
            self._left_miss_cnt += 1
            if self._left_miss_cnt > _CACHE_MAX_MISS:
                self._prev_left     = None
                self._left_miss_cnt = 0

        # 우 다항식
        if len(rx) >= 5:
            degree = 2 if len(rx) >= 80 else 1
            fit = np.polyfit(ry, rx, degree)
            fit = fit if degree == 2 else np.array([0.0, fit[0], fit[1]])
            if self._is_fit_sane(fit, h) and self._has_lane_support(rx, ry, h):
                result.right_fit      = fit
                result.right_detected = True
                self._prev_right      = fit
                self._right_miss_cnt  = 0         # 검출 성공 → 카운터 리셋
                viz[ry, rx] = (50, 50, 255)
            else:
                cv2.putText(viz, "R-FIT ERR", (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 2)
                result.right_fit  = self._prev_right
                self._right_miss_cnt += 1
                if self._right_miss_cnt > _CACHE_MAX_MISS:
                    self._prev_right     = None
                    self._right_miss_cnt = 0
        else:
            result.right_fit  = self._prev_right
            self._right_miss_cnt += 1
            if self._right_miss_cnt > _CACHE_MAX_MISS:
                self._prev_right     = None
                self._right_miss_cnt = 0

        # 다항식 곡선 그리기 + 오프셋/곡률 계산
        plot_y  = np.linspace(0, h - 1, h)

        if result.left_fit is not None and result.right_fit is not None:
            lf, rf  = result.left_fit, result.right_fit

            # 실제 검출된 픽셀 y 범위만 그리기 (엉뚱한 외삽 방지)
            ly_range = ly if result.left_detected  else np.array([h // 2, h - 1])
            ry_range = ry if result.right_detected else np.array([h // 2, h - 1])
            y_min = int(max(np.min(ly_range), np.min(ry_range)))
            y_max = h - 1
            draw_y = np.linspace(y_min, y_max, y_max - y_min + 1)

            left_x  = lf[0] * draw_y**2 + lf[1] * draw_y + lf[2]
            right_x = rf[0] * draw_y**2 + rf[1] * draw_y + rf[2]

            # 차선 채우기 (검출 구간만)
            pts_left  = np.array([np.transpose(np.vstack([left_x,  draw_y]))], dtype=np.int32)
            pts_right = np.array([np.flipud(np.transpose(np.vstack([right_x, draw_y])))], dtype=np.int32)
            pts_lane  = np.hstack((pts_left, pts_right))
            lane_img  = np.zeros_like(viz)
            cv2.fillPoly(lane_img, pts_lane, (0, 60, 0))
            viz = cv2.addWeighted(viz, 1.0, lane_img, 0.4, 0)

            # 곡선 라인 (검출 구간만)
            for pts, color in [(pts_left, (255, 180, 0)), (pts_right, (0, 180, 255))]:
                cv2.polylines(viz, pts, False, color, 3)

            # 오프셋: 하단 40% 픽셀 중앙값 기반 (외삽 오류 방지, 경계 클램핑)
            bot_thresh = int(h * 0.6)
            l_bot = lx[ly >= bot_thresh] if result.left_detected  and len(ly) > 0 else np.array([])
            r_bot = rx[ry >= bot_thresh] if result.right_detected and len(ry) > 0 else np.array([])
            y_eval = y_max
            raw_l = float(np.median(l_bot)) if len(l_bot) > 0 else lf[0]*y_eval**2+lf[1]*y_eval+lf[2]
            raw_r = float(np.median(r_bot)) if len(r_bot) > 0 else rf[0]*y_eval**2+rf[1]*y_eval+rf[2]
            left_x_bot  = float(np.clip(raw_l, 0, w))
            right_x_bot = float(np.clip(raw_r, 0, w))

            if not self._lane_pair_is_sane(lf, rf, h, w):
                cv2.putText(viz, "PAIR GEOM ERR", (10, viz.shape[0] - 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)
                result.offset_m = float("nan")
                result.viz = viz
                return result

            # BEV 경계 유효성: dst_margin 바깥이면 배리어/합류선 오검출 → 캐시 초기화
            _margin = BEV_DST_MARGIN
            if left_x_bot < _margin or right_x_bot > (w - _margin):
                label = ("L-BOUNDARY" if left_x_bot < _margin
                         else "R-BOUNDARY")
                cv2.putText(viz, label, (10, viz.shape[0] - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                result.offset_m = float("nan")
                # 잘못된 쪽 캐시 강제 초기화
                if left_x_bot < _margin:
                    self._prev_left     = None
                    self._left_miss_cnt = 0
                if right_x_bot > (w - _margin):
                    self._prev_right     = None
                    self._right_miss_cnt = 0
                result.viz = viz
                return result

            lane_center  = (left_x_bot + right_x_bot) / 2.0
            result.offset_m = (lane_center - w / 2.0) * XM_PER_PIX

            # 차선 폭 유효성: 1.5~6.5m (XM_PER_PIX 오차·곡선부 여유 포함)
            lane_w_m = (right_x_bot - left_x_bot) * XM_PER_PIX
            if not (1.5 <= lane_w_m <= 6.5):
                cv2.putText(viz, f"BAD WIDTH {lane_w_m:.1f}m", (10, viz.shape[0] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                if lane_w_m < 1.5:
                    # 우측이 좌측에 붙음 → 우측 캐시 초기화 후 단독 폴백
                    self._prev_right      = None
                    self._right_miss_cnt  = 0
                    result.right_fit      = None
                    result.right_detected = False
                    result = LaneDetector._single_lane_fallback(result, h, w, plot_y, viz)
                    result.viz = viz
                    return result
                elif result.left_detected != result.right_detected:
                    if not result.left_detected:
                        result.left_fit  = None
                    if not result.right_detected:
                        result.right_fit = None
                    result = LaneDetector._single_lane_fallback(result, h, w, plot_y, viz)
                    result.viz = viz
                    return result
                else:
                    result.offset_m = float("nan")

            # 곡률 반경 (미터) — 검출된 픽셀로만 계산
            y_eval_m = y_eval * YM_PER_PIX
            radii = []
            if result.left_detected and len(ly) >= 3:
                lf_m = np.polyfit(ly * YM_PER_PIX, lx * XM_PER_PIX, 2)
                denom = abs(2 * lf_m[0])
                if denom > 1e-6:
                    radii.append((1 + (2 * lf_m[0] * y_eval_m + lf_m[1])**2)**1.5 / denom)
            if result.right_detected and len(ry) >= 3:
                rf_m = np.polyfit(ry * YM_PER_PIX, rx * XM_PER_PIX, 2)
                denom = abs(2 * rf_m[0])
                if denom > 1e-6:
                    radii.append((1 + (2 * rf_m[0] * y_eval_m + rf_m[1])**2)**1.5 / denom)
            result.curve_radius_m = float(np.mean(radii)) if radii else 9999.0

            # HUD 텍스트
            _put_hud(viz,
                     offset=result.offset_m,
                     radius=result.curve_radius_m,
                     left_ok=result.left_detected,
                     right_ok=result.right_detected)

        elif result.left_fit is not None or result.right_fit is not None:
            if result.left_detected or result.right_detected:
                result = self._single_lane_fallback(result, h, w, plot_y, viz)
            else:
                # 캐시 전용 (실제 픽셀 없음) → nan: 컨트롤러 NO_DET 진입
                result.offset_m = float("nan")
                cv2.putText(viz, "CACHE ONLY", (10, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 80, 255), 2)

        result.viz = viz
        return result

    # ── 폴리핏 물리적 타당성 검사 ────────────────────────────────
    @staticmethod
    def _needs_sparse_recovery(result: LaneResult) -> bool:
        if result.left_detected and result.right_detected and np.isfinite(result.offset_m):
            return False
        if result.left_detected or result.right_detected:
            return not np.isfinite(result.offset_m)
        return True

    def _sparse_line_recovery(self, binary: np.ndarray, viz: Optional[np.ndarray]) -> Optional[LaneResult]:
        h, w = binary.shape
        if cv2.countNonZero(binary) < 12:
            return None

        if viz is None:
            viz = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        else:
            viz = viz.copy()

        k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 17))
        work = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k_close)
        lines = cv2.HoughLinesP(
            work,
            rho=1,
            theta=np.pi / 180.0,
            threshold=10,
            minLineLength=max(22, int(h * 0.05)),
            maxLineGap=30,
        )
        if lines is None:
            return None

        left: list[dict] = []
        right: list[dict] = []
        mid = w * 0.5
        for item in lines.reshape(-1, 4):
            x1, y1, x2, y2 = (int(v) for v in item)
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            y_span = abs(dy)
            x_span = abs(dx)
            if y_span < h * 0.07 or y_span < x_span * 0.75:
                continue

            y_max = max(y1, y2)
            y_min = min(y1, y2)
            if y_max < h * 0.50:
                continue

            fit_1d = np.polyfit(np.array([y1, y2]), np.array([x1, x2]), 1)
            fit = np.array([0.0, float(fit_1d[0]), float(fit_1d[1])])
            if not self._is_fit_sane(fit, h):
                continue

            x_bot = float(fit[0] * (h - 1) ** 2 + fit[1] * (h - 1) + fit[2])
            if x_bot < BEV_DST_MARGIN * 0.65 or x_bot > w - BEV_DST_MARGIN * 0.65:
                continue

            length = float((dx * dx + dy * dy) ** 0.5)
            score = length + y_max * 0.05 - abs(x_bot - mid) * 0.015
            road_support = y_max >= h * 0.68
            upper_origin = y_min < h * 0.38 and y_max < h * 0.78
            outer_right = x_bot > w * 0.78
            outer_left = x_bot < w * 0.22
            candidate = {
                "fit": fit,
                "x_bot": x_bot,
                "length": length,
                "score": score,
                "pts": (x1, y1, x2, y2),
                "road_support": road_support,
                "upper_origin": upper_origin,
                "outer_edge": outer_right or outer_left,
            }
            if x_bot < mid:
                left.append(candidate)
            else:
                right.append(candidate)

        result = self._recover_sparse_pair(left, right, h, w, viz)
        if result is not None:
            return result
        return self._recover_sparse_with_cache(left, right, h, w, viz)

    def _recover_sparse_pair(
        self,
        left: list[dict],
        right: list[dict],
        h: int,
        w: int,
        viz: np.ndarray,
    ) -> Optional[LaneResult]:
        best = None
        best_score = -1e9
        for l in left:
            for r in right:
                lf = l["fit"]
                rf = r["fit"]
                if not self._lane_pair_is_sane(lf, rf, h, w):
                    continue
                width_m = (float(r["x_bot"]) - float(l["x_bot"])) * XM_PER_PIX
                if not (2.4 <= width_m <= 4.8):
                    continue
                if self._looks_like_outer_object_pair(l, r):
                    continue
                score = self._score_ego_lane_pair(lf, rf, h, w)
                score += self._score_sparse_candidate_quality(l, side="left")
                score += self._score_sparse_candidate_quality(r, side="right")
                score += float(l["score"]) + float(r["score"])
                if score > best_score:
                    best_score = score
                    best = (l, r)

        if best is None:
            return None
        return self._make_sparse_result(best[0], best[1], h, w, viz, both_detected=True)

    def _recover_sparse_with_cache(
        self,
        left: list[dict],
        right: list[dict],
        h: int,
        w: int,
        viz: np.ndarray,
    ) -> Optional[LaneResult]:
        cached_pairs = []
        if left and self._prev_right is not None:
            for l in left:
                cached_pairs.append((l, {"fit": self._prev_right, "x_bot": None, "pts": None}, False))
        if right and self._prev_left is not None:
            for r in right:
                cached_pairs.append(({"fit": self._prev_left, "x_bot": None, "pts": None}, r, False))

        best = None
        best_score = -1e9
        for l, r, both_detected in cached_pairs:
            lf = l["fit"]
            rf = r["fit"]
            if not self._lane_pair_is_sane(lf, rf, h, w):
                continue
            y_eval = h - 1.0
            left_bot = float(lf[0] * y_eval**2 + lf[1] * y_eval + lf[2])
            right_bot = float(rf[0] * y_eval**2 + rf[1] * y_eval + rf[2])
            width_m = (right_bot - left_bot) * XM_PER_PIX
            if not (2.4 <= width_m <= 4.8):
                continue
            detected = l if l.get("pts") is not None else r
            if self._looks_like_outer_object_pair(l, r):
                continue
            score = self._score_ego_lane_pair(lf, rf, h, w)
            if detected is l:
                score += self._score_sparse_candidate_quality(detected, side="left")
            else:
                score += self._score_sparse_candidate_quality(detected, side="right")
            score += float(detected.get("score", 0.0))
            if score > best_score:
                best_score = score
                best = (l, r, both_detected)

        if best is None:
            return None
        return self._make_sparse_result(best[0], best[1], h, w, viz, both_detected=best[2])

    def _make_sparse_result(
        self,
        left: dict,
        right: dict,
        h: int,
        w: int,
        viz: np.ndarray,
        both_detected: bool,
    ) -> LaneResult:
        lf = left["fit"]
        rf = right["fit"]
        y_eval = h - 1.0
        left_x_bot = float(lf[0] * y_eval**2 + lf[1] * y_eval + lf[2])
        right_x_bot = float(rf[0] * y_eval**2 + rf[1] * y_eval + rf[2])
        lane_center = (left_x_bot + right_x_bot) * 0.5

        result = LaneResult()
        result.left_fit = lf
        result.right_fit = rf
        result.left_detected = bool(left.get("pts") is not None)
        result.right_detected = bool(right.get("pts") is not None)
        if both_detected:
            result.left_detected = True
            result.right_detected = True
        result.offset_m = (lane_center - w * 0.5) * XM_PER_PIX
        result.curve_radius_m = 9999.0

        self._prev_left = lf
        self._prev_right = rf
        self._left_miss_cnt = 0 if result.left_detected else self._left_miss_cnt
        self._right_miss_cnt = 0 if result.right_detected else self._right_miss_cnt

        plot_y = np.linspace(max(0, int(h * 0.35)), h - 1, h - int(h * 0.35))
        left_x = lf[0] * plot_y**2 + lf[1] * plot_y + lf[2]
        right_x = rf[0] * plot_y**2 + rf[1] * plot_y + rf[2]
        pts_left = np.array([np.transpose(np.vstack([left_x, plot_y]))], dtype=np.int32)
        pts_right = np.array([np.transpose(np.vstack([right_x, plot_y]))], dtype=np.int32)
        cv2.polylines(viz, pts_left, False, (255, 200, 0), 3)
        cv2.polylines(viz, pts_right, False, (0, 220, 255), 3)
        for item, color in ((left, (255, 80, 80)), (right, (80, 80, 255))):
            pts = item.get("pts")
            if pts is not None:
                cv2.line(viz, (pts[0], pts[1]), (pts[2], pts[3]), color, 2)
        cv2.putText(viz, "SPARSE LINE", (10, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 255), 2)
        _put_hud(viz, result.offset_m, result.curve_radius_m,
                 result.left_detected, result.right_detected)
        result.viz = viz
        return result

    def _previous_lane_center_bot(self, img_h: int) -> Optional[float]:
        if self._prev_left is None or self._prev_right is None:
            return None
        y_eval = img_h - 1.0
        left_x = float(self._prev_left[0] * y_eval**2 + self._prev_left[1] * y_eval + self._prev_left[2])
        right_x = float(self._prev_right[0] * y_eval**2 + self._prev_right[1] * y_eval + self._prev_right[2])
        return (left_x + right_x) * 0.5

    @staticmethod
    def _score_sparse_candidate_quality(candidate: dict, side: str) -> float:
        score = 0.0
        if candidate.get("road_support"):
            score += 90.0
        else:
            score -= 140.0

        if candidate.get("upper_origin"):
            score -= 80.0
        if candidate.get("outer_edge"):
            score -= 80.0

        # Right-side panels/barriers are the dominant false positive in the current scenario.
        if side == "right" and candidate.get("outer_edge") and not candidate.get("road_support"):
            score -= 240.0
        return score

    @staticmethod
    def _looks_like_outer_object_pair(left: dict, right: dict) -> bool:
        right_object = (
            right.get("pts") is not None
            and right.get("outer_edge")
            and right.get("upper_origin")
            and not right.get("road_support")
        )
        left_object = (
            left.get("pts") is not None
            and left.get("outer_edge")
            and left.get("upper_origin")
            and not left.get("road_support")
        )
        return bool(right_object or left_object)

    def _score_ego_lane_pair(
        self,
        left_fit: np.ndarray,
        right_fit: np.ndarray,
        img_h: int,
        img_w: int,
    ) -> float:
        sample_y = np.array([img_h * 0.45, img_h * 0.65, img_h - 1.0], dtype=np.float32)
        left_x = left_fit[0] * sample_y**2 + left_fit[1] * sample_y + left_fit[2]
        right_x = right_fit[0] * sample_y**2 + right_fit[1] * sample_y + right_fit[2]
        widths_m = (right_x - left_x) * XM_PER_PIX
        centers = (left_x + right_x) * 0.5

        bottom_center = float(centers[-1])
        bottom_width_m = float(widths_m[-1])
        ego_x = img_w * 0.5
        score = 0.0

        # Prefer the lane that contains the ego vehicle in near and mid BEV.
        for lx, rx in zip(left_x[1:], right_x[1:]):
            if float(lx) < ego_x < float(rx):
                score += 120.0
            else:
                outside_px = min(abs(ego_x - float(lx)), abs(ego_x - float(rx)))
                score -= outside_px * 0.7

        # Lane width around a normal 3.5m lane is more likely than adjacent/noise pairs.
        score -= abs(bottom_width_m - 3.5) * 65.0
        score -= float(np.std(widths_m)) * 45.0

        # Keep continuity with the previous ego lane to avoid jumping to adjacent lanes.
        prev_center = self._previous_lane_center_bot(img_h)
        if prev_center is not None:
            score -= abs(bottom_center - prev_center) * 0.9
        else:
            score -= abs(bottom_center - ego_x) * 0.35

        # Similar left/right slopes are more lane-like than a road edge plus object pair.
        slope_delta = abs(float(left_fit[1]) - float(right_fit[1]))
        score -= slope_delta * 60.0
        return score

    @staticmethod
    def _is_fit_sane(fit: np.ndarray, img_h: int) -> bool:
        """x=Ay²+By+C 물리적 타당성: sweep≤65%h, |B|≤0.80, |A|≤0.004"""
        if fit is None or len(fit) < 3:
            return False
        A, B, _ = float(fit[0]), float(fit[1]), float(fit[2])
        sweep    = abs(A * img_h**2 + B * img_h)
        return sweep <= img_h * 0.65 and abs(B) <= 0.80 and abs(A) <= 0.004

    @staticmethod
    def _has_lane_support(xs: np.ndarray, ys: np.ndarray, img_h: int) -> bool:
        if len(xs) < 8 or len(ys) < 8:
            return False

        y_span = float(np.max(ys) - np.min(ys))
        if y_span < img_h * 0.18:
            return False

        bottom = ys >= int(img_h * 0.62)
        bottom_count = int(np.count_nonzero(bottom))
        return bottom_count >= max(6, int(len(ys) * 0.12))

    @staticmethod
    def _lane_pair_is_sane(left_fit: np.ndarray, right_fit: np.ndarray, img_h: int, img_w: int) -> bool:
        sample_y = np.array([img_h * 0.45, img_h * 0.65, img_h - 1.0], dtype=np.float32)
        left_x = left_fit[0] * sample_y**2 + left_fit[1] * sample_y + left_fit[2]
        right_x = right_fit[0] * sample_y**2 + right_fit[1] * sample_y + right_fit[2]

        widths_m = (right_x - left_x) * XM_PER_PIX
        if np.any(widths_m < 2.0) or np.any(widths_m > 5.2):
            return False
        if float(np.max(widths_m) - np.min(widths_m)) > 1.8:
            return False

        centers = (left_x + right_x) * 0.5
        if np.any(centers < BEV_DST_MARGIN * 0.7) or np.any(centers > img_w - BEV_DST_MARGIN * 0.7):
            return False

        return True

    # ── 한쪽 차선만 검출된 경우 ──────────────────────────────────
    @staticmethod
    def _single_lane_fallback(result: LaneResult, h, w, plot_y, viz) -> LaneResult:
        """검출된 한쪽 차선으로 반대편 위치를 추정 (직선 주행 유지용)"""
        LANE_WIDTH_PX = int(3.5 / XM_PER_PIX)  # 차선폭 약 3.5m

        if result.left_fit is not None:
            lf = result.left_fit
            y_eval = h - 1
            left_x_bot = lf[0] * y_eval**2 + lf[1] * y_eval + lf[2]
            # 위치 유효성: dst_margin ≤ left_x ≤ 65%w
            if not (BEV_DST_MARGIN <= left_x_bot <= w * 0.65):
                result.offset_m = float("nan")
                cv2.putText(viz, "L-POS ERR", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)
                return result

            lx = lf[0] * plot_y**2 + lf[1] * plot_y + lf[2]
            rx = lx + LANE_WIDTH_PX
            pts_l = np.array([np.transpose(np.vstack([lx, plot_y]))], dtype=np.int32)
            cv2.polylines(viz, pts_l, False, (255, 180, 0), 3)
            right_x_bot = left_x_bot + LANE_WIDTH_PX
        else:
            rf = result.right_fit
            y_eval = h - 1
            right_x_bot = rf[0] * y_eval**2 + rf[1] * y_eval + rf[2]
            # 위치 유효성: 35%w ≤ right_x ≤ w - dst_margin
            if not (w * 0.35 <= right_x_bot <= w - BEV_DST_MARGIN):
                result.offset_m = float("nan")
                cv2.putText(viz, "R-POS ERR", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)
                return result

            rx = rf[0] * plot_y**2 + rf[1] * plot_y + rf[2]
            lx = rx - LANE_WIDTH_PX
            pts_r = np.array([np.transpose(np.vstack([rx, plot_y]))], dtype=np.int32)
            cv2.polylines(viz, pts_r, False, (0, 180, 255), 3)
            left_x_bot = right_x_bot - LANE_WIDTH_PX

        lane_center     = (left_x_bot + right_x_bot) / 2.0
        inferred_offset_m = (lane_center - w / 2.0) * XM_PER_PIX
        if abs(inferred_offset_m) > 1.25:
            result.offset_m = float("nan")
            cv2.putText(viz, "SINGLE OFFSET ERR", (10, 85),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)
            return result

        result.offset_m = (lane_center - w / 2.0) * XM_PER_PIX

        _put_hud(viz, result.offset_m, result.curve_radius_m,
                 result.left_detected, result.right_detected)
        return result


# ─── HUD 헬퍼 ───────────────────────────────────────────────────
def _put_hud(img, offset, radius, left_ok, right_ok):
    side  = "LEFT " if offset > 0 else "RIGHT"
    r_str = f"{radius:.0f}m" if radius < 5000 else "STRAIGHT"
    lines = [
        f"Offset : {abs(offset):.2f}m {side}",
        f"Radius : {r_str}",
        f"Lane   : {'L' if left_ok else '-'} {'R' if right_ok else '-'}",
    ]
    for i, txt in enumerate(lines):
        cv2.putText(img, txt, (10, 25 + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2)


if __name__ == "__main__":
    from lane_control.lane_detector_cli import main
    main()
