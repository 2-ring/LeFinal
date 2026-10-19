# SO-101 Setup Notes

## Questions

- Is servo ID setting not important?

## Steps We Completed + Details

### Important Reading

- [HiWonder SO-ARM101 User Manual — Robotic Arm Control](https://docs.hiwonder.com/projects/LeRobot/en/latest/docs/SO_ARM101_Open_Source_6_Axis_Robotic_Arm_User_Manual.html?utm_source=chatgpt.com#robotic-arm-control)

### Specific Considerations / Details

- Keep slack on the follower camera wire! The original setup through the notches doesn't allow the `wrist_roll` joint to turn and pulls on the wire.
- Remember to put on camera caps when you finish!
- Original setup observation: "Stickiness of the leader's gripper is okay, just be careful but we can move it, just needs a little extra force."
- Don't twist either of the cameras, they are set at the exact rotations for clear, unblurred vision

### 1. Conda Environment

- Set up the Conda environment with the environment.yml file in the repo root

### 2. LeRobot Download

- Download LeRobot zip from Section 2.2.2 of HiWonder docs
  - https://docs.hiwonder.com/projects/LeRobot/en/latest/docs/SO_ARM101_Open_Source_6_Axis_Robotic_Arm_User_Manual.html
- Don't put it in the repo

### 3. LeRobot & Feetech (Servo Driver) Installation
- Make sure the conda env is activated and run this to install

```bash
python -m pip install -e ".[feetech]"
```

### 4. Identify Servo Ports

```bash
lerobot-find-port
```

| Arm | Recorded port |
| --- | --- |
| Follower | `/dev/tty.usbmodem5C4C1243751` |
| Leader | `/dev/tty.usbmodem5C821083221` |

NOTE: These might be different on another computer!

### 5. Calibrate Leader

Recalibrated because the gripper was being a bit annoying.

```bash
lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5C821083221 \
  --teleop.id=hiwonder_leader_01
```

Saved to:

```text
/Users/rohitchawla/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/hiwonder_leader_01.json
```

### 6. Calibrate Follower

```bash
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5C4C1243751 \
  --robot.id=hiwonder_follower_01
```

Saved to:

```text
/Users/rohitchawla/.cache/huggingface/lerobot/calibration/robots/so101_follower/hiwonder_follower_01.json
```

### 7. Teleoperation Without Vision

```bash
python -m lerobot.teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5C4C1243751 \
  --robot.id=hiwonder_follower_01 \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5C821083221 \
  --teleop.id=hiwonder_leader_01
```

### 8. Find Cameras and Identify Their Indices

```bash
lerobot-find-cameras opencv
```

| Camera | Index | Identification / observation |
| --- | --- | --- |
| `opencv_0` | 0 | Follower camera |
| `opencv_1` | 1 | Stand camera |
| `opencv_2` | 2 | Unknown; showed a black screen |
| `opencv_3` | 3 | MacBook camera |

NOTE: these will be different on another computer!

### 9. Teleoperation With Vision

- The stand camera **must** be able to see the follower gripper and task space.
- The stand camera **must** be out of reach of the arms.

## Calibration Results

### Follower

| Name | MIN | POS | MAX |
| --- | ---: | ---: | ---: |
| `shoulder_pan` | 757 | 2114 | 3322 |
| `shoulder_lift` | 880 | 2007 | 3224 |
| `elbow_flex` | 884 | 2187 | 3079 |
| `wrist_flex` | 924 | 932 | 3067 |
| `wrist_roll` | 127 | 410 | 3950 |
| `gripper` | 1169 | 1832 | 3060 |

### Leader

| Name | MIN | POS | MAX |
| --- | ---: | ---: | ---: |
| `shoulder_pan` | 760 | 2036 | 3288 |
| `shoulder_lift` | 883 | 1897 | 3266 |
| `elbow_flex` | 876 | 1887 | 3070 |
| `wrist_flex` | 991 | 1959 | 3147 |
| `wrist_roll` | 180 | 2076 | 3994 |

## Miscellaneous Information

- We have the **Advanced kit** (both cameras).

Teleoperator and robot arguments:

```text
--teleop.id=hiwonder_leader_01
--teleop.type=so101_leader

--robot.id=hiwonder_follower_01
--robot.type=so101_follower
```
