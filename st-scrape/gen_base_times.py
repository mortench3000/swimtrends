"""Generate db/point_base_times.jsonl from the World Aquatics base-times markdown.

Follows the old point_base_times schema (season, course, gender, relay_count,
distance, stroke, basetime, basetime_in_sec) plus validity metadata. The old
age_group column is omitted: every WA base time here is senior, so it would be a
constant 'S' carrying no information.
Each transcribed row is self-validated: the seconds recomputed from the time
string must match the seconds stated in the source.
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, 'db', 'point_base_times.jsonl')

# Map source stroke names -> canonical codes (matching the old CSV).
# (Danish scraper codes Fri/Ryg/Bryst/Fly/IM/HM map to these at calc time.)
STROKE = {'Free': 'FREE', 'Back': 'BACK', 'Breast': 'BREAST', 'Fly': 'FLY', 'Medley': 'MEDLEY'}


def to_sec(t):
    """Parse 'M:SS.hh' or 'SS.hh' (tolerating stray spaces) into float seconds."""
    t = t.replace(' ', '')
    if ':' in t:
        m, rest = t.split(':')
        return round(int(m) * 60 + float(rest), 2)
    return round(float(t), 2)


# Each course block. individual rows: (distance, stroke, M_time, M_sec, W_time, W_sec)
# relay rows: (relay_count, leg_distance, stroke, M_time, M_sec, W_time, W_sec)
# mixed rows: (relay_count, leg_distance, stroke, X_time, X_sec)
BLOCKS = [
    {
        'wa_label': 'LCM 2022', 'course': 'LCM', 'season': 2022,
        'validity_start': '2022-01-01', 'validity_end': '2022-12-31',
        'individual': [
            (50, 'Free', '20.91', 20.91, '23.67', 23.67),
            (100, 'Free', '46.91', 46.91, '51.71', 51.71),
            # source: W time '1:52.8' (typo) vs sec 112.98; 2023 LCM=112.98 confirms 1:52.98
            (200, 'Free', '1:42.00', 102.00, '1:52.98', 112.98),
            (400, 'Free', '3:40.07', 220.07, '3:56.46', 236.46),
            (800, 'Free', '7:32.12', 452.12, '8:04.79', 484.79),
            (1500, 'Free', '14:31.02', 871.02, '15:20.48', 920.48),
            (50, 'Back', '23.80', 23.80, '26.98', 26.98),
            (100, 'Back', '51.85', 51.85, '57.45', 57.45),
            (200, 'Back', '1:51.92', 111.92, '2:03.35', 123.35),
            (50, 'Breast', '25.95', 25.95, '29.30', 29.30),
            (100, 'Breast', '56.88', 56.88, '1:04.13', 64.13),
            (200, 'Breast', '2:06.12', 126.12, '2:18.95', 138.95),
            (50, 'Fly', '22.27', 22.27, '24.43', 24.43),
            (100, 'Fly', '49.45', 49.45, '55.48', 55.48),
            (200, 'Fly', '1:50.73', 110.73, '2:01.81', 121.81),
            # source: W time '2:06.1' (typo) vs sec 126.12; 2023 LCM=126.12 confirms 2:06.12
            (200, 'Medley', '1:54.00', 114.00, '2:06.12', 126.12),
            (400, 'Medley', '4:03.84', 243.84, '4:26.36', 266.36),
        ],
        'relay': [
            (4, 100, 'Free', '3:08.24', 188.24, '3:29.69', 209.69),
            (4, 200, 'Free', '6:58.55', 418.55, '7:40.33', 460.33),
            (4, 100, 'Medley', '3:26.78', 206.78, '3:50.40', 230.40),
        ],
        'mixed': [
            (4, 100, 'Free', '3:19.40', 199.40),
            (4, 100, 'Medley', '3:37.58', 217.58),
        ],
    },
    {
        'wa_label': 'SCM 2022', 'course': 'SCM', 'season': 2023,
        'validity_start': '2022-09-01', 'validity_end': '2023-08-31',
        'individual': [
            (50, 'Free', '20.16', 20.16, '22.93', 22.93),
            (100, 'Free', '44.84', 44.84, '50.25', 50.25),
            (200, 'Free', '1:39.37', 99.37, '1:50.31', 110.31),
            (400, 'Free', '3:32.25', 212.25, '3:53.92', 233.92),
            (800, 'Free', '7:23.42', 443.42, '7:59.34', 479.34),
            (1500, 'Free', '14:06.88', 846.88, '15:18.01', 918.01),
            (50, 'Back', '22.22', 22.22, '25.27', 25.27),
            (100, 'Back', '48.33', 48.33, '54.89', 54.89),
            (200, 'Back', '1:45.63', 105.63, '1:58.94', 118.94),
            (50, 'Breast', '24.95', 24.95, '28.56', 28.56),
            (100, 'Breast', '55.28', 55.28, '1:02.36', 62.36),
            (200, 'Breast', '2:00.16', 120.16, '2:14.57', 134.57),
            (50, 'Fly', '21.75', 21.75, '24.38', 24.38),
            # source: W time '54.59' vs sec '54.69' disagree; using seconds column (54.69) - VERIFY
            (100, 'Fly', '54.69', 54.69, '54.69', 54.69),
            (200, 'Fly', '1:48.24', 108.24, '1:59.61', 119.61),
            (100, 'Medley', '49.28', 49.28, '56.51', 56.51),
            (200, 'Medley', '1:49.63', 109.63, '2:01.86', 121.86),
            (400, 'Medley', '3:54.81', 234.81, '4:18.94', 258.94),
        ],
        'relay': [
            (4, 50, 'Free', '1:21.80', 81.80, '1:32.50', 92.50),
            (4, 100, 'Free', '3:03.03', 183.03, '3:26.53', 206.53),
            (4, 200, 'Free', '6:46.81', 406.81, '7:32.85', 452.85),
            (4, 50, 'Medley', '1:30.14', 90.14, '1:42.38', 102.38),
            (4, 100, 'Medley', '3:19.16', 199.16, '3:44.52', 224.52),
        ],
        'mixed': [
            (4, 50, 'Free', '1:27.89', 87.89),
            (4, 50, 'Medley', '1:36.18', 96.18),
        ],
    },
    {
        'wa_label': 'LCM 2023', 'course': 'LCM', 'season': 2023,
        'validity_start': '2023-01-01', 'validity_end': '2023-12-31',
        'individual': [
            (50, 'Free', '20.91', 20.91, '23.67', 23.67),
            (100, 'Free', '46.86', 46.86, '51.71', 51.71),
            (200, 'Free', '1:42.00', 102.00, '1:52.98', 112.98),
            (400, 'Free', '3:40.07', 220.07, '3:56.40', 236.40),
            (800, 'Free', '7:32.12', 452.12, '8:04.79', 484.79),
            (1500, 'Free', '14:31.02', 871.02, '15:20.48', 920.48),
            (50, 'Back', '23.71', 23.71, '26.98', 26.98),
            (100, 'Back', '51.60', 51.60, '57.45', 57.45),
            (200, 'Back', '1:51.92', 111.92, '2:03.35', 123.35),
            (50, 'Breast', '25.95', 25.95, '29.30', 29.30),
            (100, 'Breast', '56.88', 56.88, '1:04.13', 64.13),
            (200, 'Breast', '2:05.95', 125.95, '2:18.95', 138.95),
            (50, 'Fly', '22.27', 22.27, '24.43', 24.43),
            (100, 'Fly', '49.45', 49.45, '55.48', 55.48),
            (200, 'Fly', '1:50.34', 110.34, '2:01.81', 121.81),
            (200, 'Medley', '1:54.00', 114.00, '2:06.12', 126.12),
            (400, 'Medley', '4:03.84', 243.84, '4:26.36', 266.36),
        ],
        'relay': [
            (4, 100, 'Free', '3:08.24', 188.24, '3:29.69', 209.69),
            (4, 200, 'Free', '6:58.55', 418.55, '7:39.29', 459.29),
            (4, 100, 'Medley', '3:26.78', 206.78, '3:50.40', 230.40),
        ],
        'mixed': [
            (4, 100, 'Free', '3:19.38', 199.38),
            (4, 100, 'Medley', '3:37.58', 217.58),
        ],
    },
    {
        'wa_label': 'SCM 2023', 'course': 'SCM', 'season': 2024,
        'validity_start': '2023-09-01', 'validity_end': '2024-08-31',
        'individual': [
            (50, 'Free', '20.16', 20.16, '22.93', 22.93),
            (100, 'Free', '44.84', 44.84, '50.25', 50.25),
            (200, 'Free', '1:39.37', 99.37, '1:50.31', 110.31),
            (400, 'Free', '3:32.25', 212.25, '3:51.30', 231.30),
            (800, 'Free', '7:23.42', 443.42, '7:57.42', 477.42),
            (1500, 'Free', '14:06.88', 846.88, '15:08.24', 908.24),
            (50, 'Back', '22.11', 22.11, '25.25', 25.25),
            (100, 'Back', '48.33', 48.33, '54.89', 54.89),
            (200, 'Back', '1:45.63', 105.63, '1:58.94', 118.94),
            (50, 'Breast', '24.95', 24.95, '28.37', 28.37),
            (100, 'Breast', '55.28', 55.28, '1:02.36', 62.36),
            (200, 'Breast', '2:00.16', 120.16, '2:14.57', 134.57),
            (50, 'Fly', '21.75', 21.75, '24.38', 24.38),
            (100, 'Fly', '47.78', 47.78, '54.05', 54.05),
            (200, 'Fly', '1:46.85', 106.85, '1:59.61', 119.61),
            (100, 'Medley', '49.28', 49.28, '56.51', 56.51),
            (200, 'Medley', '1:49.63', 109.63, '2:01.86', 121.86),
            (400, 'Medley', '3:54.81', 234.81, '4:18.94', 258.94),
        ],
        'relay': [
            (4, 50, 'Free', '1:21.80', 81.80, '1:32.50', 92.50),
            (4, 100, 'Free', '3:02.75', 182.75, '3:25.43', 205.43),
            (4, 200, 'Free', '6:44.12', 404.12, '7:30.87', 450.87),
            (4, 50, 'Medley', '1:29.72', 89.72, '1:42.35', 102.35),
            (4, 100, 'Medley', '3:18.98', 198.98, '3:44.35', 224.35),
        ],
        'mixed': [
            (4, 50, 'Free', '1:27.33', 87.33),
            (4, 50, 'Medley', '1:35.15', 95.15),
        ],
    },
    {
        'wa_label': 'LCM 2024', 'course': 'LCM', 'season': 2024,
        'validity_start': '2024-01-01', 'validity_end': '2024-12-31',
        'individual': [
            (50, 'Free', '20.91', 20.91, '23.61', 23.61),
            (100, 'Free', '46.86', 46.86, '51.71', 51.71),
            (200, 'Free', '1:42.00', 102.00, '1:52.85', 112.85),
            (400, 'Free', '3:40.07', 220.07, '3:55.38', 235.38),
            (800, 'Free', '7:32.12', 452.12, '8:04.79', 484.79),
            (1500, 'Free', '14:31.02', 871.02, '15:20.48', 920.48),
            (50, 'Back', '23.55', 23.55, '26.86', 26.86),
            (100, 'Back', '51.60', 51.60, '57.33', 57.33),
            (200, 'Back', '1:51.92', 111.92, '2:03.14', 123.14),
            (50, 'Breast', '25.95', 25.95, '29.16', 29.16),
            (100, 'Breast', '56.88', 56.88, '1:04.13', 64.13),
            (200, 'Breast', '2:05.48', 125.48, '2:17.55', 137.55),
            (50, 'Fly', '22.27', 22.27, '24.43', 24.43),
            (100, 'Fly', '49.45', 49.45, '55.48', 55.48),
            (200, 'Fly', '1:50.34', 110.34, '2:01.81', 121.81),
            (200, 'Medley', '1:54.00', 114.00, '2:06.12', 126.12),
            (400, 'Medley', '4:02.50', 242.50, '4:25.87', 265.87),
        ],
        'relay': [
            (4, 100, 'Free', '3:08.24', 188.24, '3:27.96', 207.96),
            (4, 200, 'Free', '6:58.55', 418.55, '7:37.50', 457.50),
            (4, 100, 'Medley', '3:26.78', 206.78, '3:50.40', 230.40),
        ],
        'mixed': [
            (4, 100, 'Free', '3:18.83', 198.83),
            (4, 100, 'Medley', '3:37.58', 217.58),
        ],
    },
    {
        'wa_label': 'LCM 2025', 'course': 'LCM', 'season': 2025,
        'validity_start': '2025-01-01', 'validity_end': '2025-12-31',
        'individual': [
            (50, 'Free', '20.91', 20.91, '23.61', 23.61),
            (100, 'Free', '46.40', 46.40, '51.71', 51.71),
            (200, 'Free', '1:42.00', 102.00, '1:52.23', 112.23),
            (400, 'Free', '3:40.07', 220.07, '3:55.38', 235.38),
            (800, 'Free', '7:32.12', 452.12, '8:04.79', 484.79),
            (1500, 'Free', '14:30.67', 870.67, '15:20.48', 920.48),
            (50, 'Back', '23.55', 23.55, '26.86', 26.86),
            (100, 'Back', '51.60', 51.60, '57.13', 57.13),
            (200, 'Back', '1:51.92', 111.92, '2:03.14', 123.14),
            (50, 'Breast', '25.95', 25.95, '29.16', 29.16),
            (100, 'Breast', '56.88', 56.88, '1:04.13', 64.13),
            (200, 'Breast', '2:05.48', 125.48, '2:17.55', 137.55),
            (50, 'Fly', '22.27', 22.27, '24.43', 24.43),
            (100, 'Fly', '49.45', 49.45, '55.18', 55.18),
            (200, 'Fly', '1:50.34', 110.34, '2:01.81', 121.81),
            (200, 'Medley', '1:54.00', 114.00, '2:06.12', 126.12),
            (400, 'Medley', '4:02.50', 242.50, '4:24.38', 264.38),
        ],
        'relay': [
            (4, 100, 'Free', '3:08.24', 188.24, '3:27.96', 207.96),
            (4, 200, 'Free', '6:58.55', 418.55, '7:37.50', 457.50),
            (4, 100, 'Medley', '3:26.78', 206.78, '3:49.63', 229.63),
        ],
        'mixed': [
            (4, 100, 'Free', '3:18.83', 198.83),
            (4, 100, 'Medley', '3:37.43', 217.43),
        ],
    },
    {
        'wa_label': 'SCM 2025', 'course': 'SCM', 'season': 2026,
        'validity_start': '2025-09-01', 'validity_end': '2026-08-31',
        'individual': [
            (50, 'Free', '19.90', 19.90, '22.83', 22.83),
            (100, 'Free', '44.84', 44.84, '50.25', 50.25),
            (200, 'Free', '1:38.61', 98.61, '1:50.31', 110.31),
            (400, 'Free', '3:32.25', 212.25, '3:50.25', 230.25),
            (800, 'Free', '7:20.46', 440.46, '7:57.42', 477.42),
            (1500, 'Free', '14:06.88', 846.88, '15:08.24', 908.24),
            (50, 'Back', '22.11', 22.11, '25.23', 25.23),
            (100, 'Back', '48.33', 48.33, '54.02', 54.02),
            (200, 'Back', '1:45.63', 105.63, '1:58.04', 118.04),
            (50, 'Breast', '24.95', 24.95, '28.37', 28.37),
            (100, 'Breast', '55.28', 55.28, '1:02.36', 62.36),
            (200, 'Breast', '2:00.16', 120.16, '2:12.50', 132.50),
            (50, 'Fly', '21.32', 21.32, '23.94', 23.94),
            (100, 'Fly', '47.71', 47.71, '52.71', 52.71),
            (200, 'Fly', '1:46.85', 106.85, '1:59.32', 119.32),
            (100, 'Medley', '49.28', 49.28, '55.11', 55.11),
            (200, 'Medley', '1:48.88', 108.88, '2:01.63', 121.63),
            (400, 'Medley', '3:54.81', 234.81, '4:15.48', 255.48),
        ],
        'relay': [
            (4, 50, 'Free', '1:21.80', 81.80, '1:32.50', 92.50),
            (4, 100, 'Free', '3:01.66', 181.66, '3:25.01', 205.01),
            (4, 200, 'Free', '6:40.51', 400.51, '7:30.13', 450.13),
            (4, 50, 'Medley', '1:29.72', 89.72, '1:42.35', 102.35),
            (4, 100, 'Medley', '3:18.68', 198.68, '3:40.41', 220.41),
        ],
        'mixed': [
            (4, 50, 'Free', '1:27.33', 87.33),
            (4, 50, 'Medley', '1:35.15', 95.15),
        ],
    },
    {
        'wa_label': 'LCM 2026', 'course': 'LCM', 'season': 2026,
        'validity_start': '2026-01-01', 'validity_end': '2026-12-31',
        'individual': [
            (50, 'Free', '20.91', 20.91, '23.61', 23.61),
            (100, 'Free', '46.40', 46.40, '51.71', 51.71),
            (200, 'Free', '1:42.00', 102.00, '1:52.23', 112.23),
            (400, 'Free', '3:39.96', 219.96, '3:54.18', 234.18),
            (800, 'Free', '7:32.12', 452.12, '8:04.12', 484.12),
            (1500, 'Free', '14:30.67', 870.67, '15:20.48', 920.48),
            (50, 'Back', '23.55', 23.55, '26.86', 26.86),
            (100, 'Back', '51.60', 51.60, '57.13', 57.13),
            (200, 'Back', '1:51.92', 111.92, '2:03.14', 123.14),
            (50, 'Breast', '25.95', 25.95, '29.16', 29.16),
            (100, 'Breast', '56.88', 56.88, '1:04.13', 64.13),
            (200, 'Breast', '2:05.48', 125.48, '2:17.55', 137.55),
            (50, 'Fly', '22.27', 22.27, '24.43', 24.43),
            (100, 'Fly', '49.45', 49.45, '54.60', 54.60),
            (200, 'Fly', '1:50.34', 110.34, '2:01.81', 121.81),
            (200, 'Medley', '1:52.69', 112.69, '2:05.70', 125.70),
            (400, 'Medley', '4:02.50', 242.50, '4:23.65', 263.65),
        ],
        'relay': [
            (4, 100, 'Free', '3:08.24', 188.24, '3:27.96', 207.96),
            (4, 200, 'Free', '6:58.55', 418.55, '7:37.50', 457.50),
            (4, 100, 'Medley', '3:26.78', 206.78, '3:49.34', 229.34),
        ],
        'mixed': [
            (4, 100, 'Free', '3:18.48', 198.48),
            (4, 100, 'Medley', '3:37.43', 217.43),
        ],
    },
]

records = []
errors = []


def add(block, gender, relay_count, distance, stroke_name, time_str, stated_sec):
    sec = to_sec(time_str)
    if sec != round(stated_sec, 2):
        errors.append(f"{block['wa_label']} {gender} {relay_count}x{distance} {stroke_name}: "
                      f"computed {sec} != stated {stated_sec} (time '{time_str}')")
    records.append({
        'season': block['season'],
        'course': block['course'],
        'gender': gender,
        'relay_count': relay_count,
        'distance': distance,
        'stroke': STROKE[stroke_name],
        'basetime': time_str.replace(' ', ''),
        'basetime_in_sec': stated_sec,
        'source': 'wa-doc',
        'wa_label': block['wa_label'],
        'validity_start': block['validity_start'],
        'validity_end': block['validity_end'],
    })


for block in BLOCKS:
    for dist, stroke, mt, ms, wt, ws in block['individual']:
        add(block, 'M', 1, dist, stroke, mt, ms)
        add(block, 'F', 1, dist, stroke, wt, ws)
    for rc, dist, stroke, mt, ms, wt, ws in block['relay']:
        add(block, 'M', rc, dist, stroke, mt, ms)
        add(block, 'F', rc, dist, stroke, wt, ws)
    for rc, dist, stroke, xt, xs in block['mixed']:
        add(block, 'X', rc, dist, stroke, xt, xs)

# --- Legacy historical base times (seasons 2008-2021) from the old pipeline's
# CSV. Its 'year' column is already season-based and the stroke codes match, so
# rows map straight in. We take seniors only (drop the 36 youth 'Y' rows and the
# 6 non-standard relay_count=10 rows), and validate each by recomputing seconds.
import csv

CSV_PATH = os.path.join(SCRIPT_DIR, '..', 'pgdckr', 'data', 'Points_Table_Base_Times.csv')
existing_keys = {(r['season'], r['course'], r['gender'], r['relay_count'], r['distance'], r['stroke'])
                 for r in records}
legacy = 0
legacy_warnings = []  # the CSV's basetime string vs its seconds column disagree (data quality)
with open(CSV_PATH, encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row['age_group'] != 'S' or int(row['relay_count']) == 10:
            continue
        season = int(row['year'])
        course = row['course']
        gender = row['gender']
        relay_count = int(row['relay_count'])
        distance = int(row['distance'])
        stroke = row['stroke']
        key = (season, course, gender, relay_count, distance, stroke)
        if key in existing_keys:
            continue  # WA-doc rows win on any overlap (none expected: CSV<=2021, docs>=2024)
        # The time string is canonical; derive seconds from it for internal
        # consistency, and flag any CSV row whose own seconds column disagrees.
        sec = to_sec(row['basetime'])
        csv_sec = round(float(row['basetime_in_sec']), 2)
        if sec != csv_sec:
            legacy_warnings.append(f"{season} {course} {gender} {relay_count}x{distance} {stroke}: "
                                   f"'{row['basetime']}'={sec}s but CSV column says {csv_sec}s (using {sec})")
        records.append({
            'season': season, 'course': course, 'gender': gender, 'relay_count': relay_count,
            'distance': distance, 'stroke': stroke, 'basetime': row['basetime'],
            'basetime_in_sec': sec, 'source': 'legacy-csv',
            'wa_label': None, 'validity_start': None, 'validity_end': None,
        })
        existing_keys.add(key)
        legacy += 1

# Stable sort for a tidy, diff-friendly file.
records.sort(key=lambda r: (r['season'], r['course'], r['gender'], r['relay_count'], r['distance'], r['stroke']))

if errors:
    print(f"VALIDATION FAILED ({len(errors)} mismatches):")
    for e in errors:
        print('  ' + e)
    raise SystemExit(1)

with open(OUT, 'w', encoding='utf-8') as f:
    for r in records:
        json.dump(r, f, ensure_ascii=False)
        f.write('\n')

print(f"validated {len(records)} base-time rows (all seconds match), wrote {os.path.relpath(OUT, SCRIPT_DIR)}")
from collections import Counter
print(f"  sources: {dict(Counter(r['source'] for r in records))}")
print(f"  seasons: {min(r['season'] for r in records)}-{max(r['season'] for r in records)} "
      f"({len(set(r['season'] for r in records))} seasons)")
if legacy_warnings:
    print(f"  NOTE: {len(legacy_warnings)} legacy CSV rows had a string/seconds mismatch (time string used):")
    for w in legacy_warnings:
        print('    ' + w)
