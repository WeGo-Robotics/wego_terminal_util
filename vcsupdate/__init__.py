"""vcsupdate — runtime-credential vcstool meta-repo updater for remote robots.

Operator runs the GUI on their own PC, connects over SSH (paramiko) to a remote
robot, and updates a vcstool-managed meta workspace. Git credentials are injected
at runtime via SSH agent forwarding, so no key is ever persisted on the robot.
"""
