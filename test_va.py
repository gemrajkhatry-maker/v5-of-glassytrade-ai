from dataclasses import dataclass

@dataclass
class VolumeProfileLevel:
    price: float
    volume: float

def compute_va(profile, poc_index, target_volume):
    current_volume = profile[poc_index].volume
    up_idx = poc_index
    down_idx = poc_index

    while current_volume < target_volume:
        up_pair = 0.0
        up_count = 0
        for k in range(1, 3):
            if up_idx + k < len(profile):
                up_pair += profile[up_idx + k].volume
                up_count += 1

        down_pair = 0.0
        down_count = 0
        for k in range(1, 3):
            if down_idx - k >= 0:
                down_pair += profile[down_idx - k].volume
                down_count += 1

        can_go_up = up_count > 0
        can_go_down = down_count > 0

        if not can_go_up and not can_go_down:
            break

        up_avg = up_pair / up_count if up_count else 0.0
        down_avg = down_pair / down_count if down_count else 0.0

        if can_go_up and (not can_go_down or up_avg >= down_avg):
            for k in range(1, up_count + 1):
                if up_idx + k < len(profile):
                    up_idx += 1
                    current_volume += profile[up_idx].volume
                else:
                    print(f"Skipped up! k={k}, up_idx={up_idx}")
        elif can_go_down:
            for k in range(1, down_count + 1):
                if down_idx - k >= 0:
                    down_idx -= 1
                    current_volume += profile[down_idx].volume
                else:
                    print(f"Skipped down! k={k}, down_idx={down_idx}")

    return up_idx, down_idx

prof = [VolumeProfileLevel(p, 10.0) for p in range(5)]
prof[2].volume = 20.0
print("Buggy result:", compute_va(prof, 2, 60.0))
