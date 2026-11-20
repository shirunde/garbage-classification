"""Compare the target bin before and after one fixed-point placement."""

import json

from shared.schemas import CLASSES


def load_bin_rois(path):
    rois = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(rois, dict) or not rois:
        raise ValueError('投放区标定文件须包含类别和对应的像素矩形')
    for category, box in rois.items():
        if category not in CLASSES or not isinstance(box, list) or len(box) != 4:
            raise ValueError(f'无效的投放区配置：{category}')
        if any(type(value) is not int for value in box):
            raise ValueError(f'{category} 的投放区坐标必须为整数')
        left, top, right, bottom = box
        if not (0 <= left < right <= 640 and 0 <= top < bottom <= 480):
            raise ValueError(f'{category} 的投放区超出 640×480 画面')
    return rois


class PlacementCheck:
    def __init__(self, cv2, read_frame, detector, rois, photo_prefix, record, min_confidence):
        self.cv2 = cv2
        self.read_frame = read_frame
        self.detector = detector
        self.rois = rois
        self.photo_prefix = photo_prefix
        self.record = record
        self.min_confidence = min_confidence
        self.camera_views = {}
        self.move_camera = None
        self.center_view = None
        self.verify_photo = None
        self.record['result'] = 'unverified'

    def capture(self, stage, target):
        if self.move_camera is not None and stage == 'before':
            return False
        view = self.camera_views.get(target.cls)
        if self.move_camera is not None and view is None:
            self.record['limitation'] = '该类别的投放相机观察角尚未示教'
            print(self.record['limitation'], flush=True)
            return False
        if view is None:
            return self._capture(stage, target)
        self.record['camera_base_deg'], self.record['camera_shoulder_deg'] = view
        self.move_camera(view)
        self._capture(stage, target, photo_only=True)
        self.move_camera(self.center_view)
        photo = self.record[stage].get('photo')
        if self.verify_photo is not None and photo:
            try:
                verdict = self.verify_photo(target.cls, photo)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.record['model_error'] = str(exc)
                print(f'千问核验暂不可用：{exc}', flush=True)
            else:
                self.record['model_status'] = verdict
                if verdict == 'in_bin':
                    self.record['result'] = 'placement_confirmed'
                    return True
                if verdict == 'not_in_bin':
                    self.record['result'] = 'placement_failed'
        return False

    def _capture(self, stage, target, photo_only=False):
        box = self.rois.get(target.cls)
        self.record['roi'] = box
        sample = {'detections': []}
        self.record[stage] = sample
        in_bin = []
        try:
            for _ in range(3):
                self.read_frame()
            for index in range(3):
                frame = self.read_frame()
                if index == 0:
                    path = self.photo_prefix.with_name(f'{self.photo_prefix.name}_{stage}.jpg')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if self.cv2.imwrite(str(path), frame):
                        sample['photo'] = str(path)
                        print(f"投放{'前' if stage == 'before' else '后'}照片：{path}", flush=True)
                    elif photo_only:
                        raise OSError("无法写入落点照片")
                if photo_only:
                    return False
                found = self.detector.detect_all(frame)
                sample['detections'].append([dict(item.__dict__) for item in found])
                if box:
                    left, top, right, bottom = box
                    in_bin.append([item for item in found if left <= item.u < right and top <= item.v < bottom])
        except Exception as exc:
            sample['error'] = str(exc)
            print(f'落点核验采集失败：{exc}', flush=True)
            return False
        sample['empty'] = bool(box) and not any(in_bin)
        if stage == 'before':
            return False
        matches = sum(any(item.cls == target.cls and item.conf >= self.min_confidence
                          for item in frame) for frame in in_bin)
        sample['matching_frames'] = matches
        if self.record.get('before', {}).get('empty') and matches >= 2:
            self.record['result'] = 'placement_confirmed'
            return True
        return False
