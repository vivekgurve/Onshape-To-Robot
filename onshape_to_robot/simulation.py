#!/usr/bin/env python
from transforms3d.quaternions import mat2quat, quat2mat
import math
import sys
import time
import numpy as np
import pybullet as p
from time import sleep
import os
import re


class Simulation:
    """
    A Bullet simulation involving Sigmaban humanoid robot
    """

    def __init__(self, robotPath, floor=True, fixed=False, transparent=False, gui=True, realTime=True, panels=False):
        """Creates an instance of humanoid simulation

        Keyword Arguments:
            field {bool} -- enable the display of the field (default: {False})
            fixed {bool} -- makes the robot floating/fixed (default: {False})
            transparent {bool} -- makes the robot transparent (default: {False})
            gui {bool} -- enables the gui visualizer, if False it will runs headless (default {True})
            realTime {bool} -- try to have simulation in real time (default {True})
            panels {bool} -- show/hide the user interaction pyBullet panels
        """

        self.dir = os.path.dirname(os.path.abspath(__file__))
        self.gui = gui
        self.realTime = realTime
        self.t = 0
        self.start = time.time()
        self.dt = 0.005

        # Debug lines drawing
        self.lines = []
        self.currentLine = 0
        self.lastLinesDraw = 0
        self.lineColors = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1]]

        # Instanciating bullet
        if gui:
            physicsClient = p.connect(p.GUI)
        else:
            physicsClient = p.connect(p.DIRECT)
        p.setGravity(0, 0, -9.81)

        # Light GUI
        if not panels:
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_SEGMENTATION_MARK_PREVIEW, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_DEPTH_BUFFER_PREVIEW, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_RGB_BUFFER_PREVIEW, 0)
            
        p.configureDebugVisualizer(p.COV_ENABLE_MOUSE_PICKING, 1)

        # Loading floor and/or plane ground
        if floor:
            self.floor = p.loadURDF(self.dir+'/bullet/plane.urdf')
        else:
            self.floor = None

        # Loading robot
        startPos = [0, 0, 1]
        startOrientation = p.getQuaternionFromEuler([0, 0, 0])
        self.robot = p.loadURDF(robotPath,
                                startPos, startOrientation,
                                flags=p.URDF_USE_SELF_COLLISION, useFixedBase=fixed)

        # Ball is loaded when needed
        self.ball = None

        # Setting frictions parameters to default ones
        self.setFloorFrictions()

        # Engine parameters
        p.setPhysicsEngineParameter(fixedTimeStep=self.dt, maxNumCmdPer1ms=0)
        # p.setRealTimeSimulation(0)
        # p.setPhysicsEngineParameter(numSubSteps=1)

        # Retrieving joints and frames
        self.joints = {}
        self.jointsIndexes = {}
        self.frames = {}

        # Collecting the available joints
        n = 0
        for k in range(p.getNumJoints(self.robot)):
            jointInfo = p.getJointInfo(self.robot, k)
            name = jointInfo[1].decode('utf-8')
            if '_fixing' not in name:
                if '_frame' in name:
                    self.frames[name] = k
                else:
                    self.jointsIndexes[name] = n
                    n += 1
                    self.joints[name] = k

        # Changing robot opacity if transparent set to true
        if transparent:
            for k in range(p.getNumJoints(self.robot)):
                p.changeVisualShape(self.robot, k, rgbaColor=[
                                    0.3, 0.3, 0.3, 0.3])

        print('* Found '+str(len(self.joints))+' DOFs')
        print('* Found '+str(len(self.frames))+' frames')

    def setFloorFrictions(self, lateral=0.8, spinning=0.1, rolling=0.1):
        """Sets the frictions with the plane object

        Keyword Arguments:
            lateral {float} -- lateral friction (default: {0.8})
            spinning {float} -- spinning friction (default: {0.1})
            rolling {float} -- rolling friction (default: {0.1})
        """
        if self.floor is not None:
            p.changeDynamics(self.floor, -1, lateralFriction=lateral,
                            spinningFriction=spinning, rollingFriction=rolling)

    def lookAt(self, target):
        """Control the look of the visualizer camera

        Arguments:
            target {tuple} -- target as (x,y,z) tuple
        """
        if self.gui:
            params = p.getDebugVisualizerCamera()
            p.resetDebugVisualizerCamera(params[10], params[8], params[9], target)

    def getRobotPose(self):
        """Gets the robot (origin) position

        Returns:
            (tuple(3), tuple(3)) -- (x,y,z), (roll, pitch, yaw)
        """
        pose = p.getBasePositionAndOrientation()
        return (pose[0], p.getEulerFromQuaternion(pose[1]))

    def frameToWorldMatrix(self, frame):
        """Gets the given frame to world matrix transformation. can be a frame name
        from URDF/SDF or "origin" for the part origin

        Arguments:
            frame {str} -- frame name

        Returns:
            np.matrix -- a 4x4 matrix
        """

        if frame == 'origin':
            frameToWorldPose = p.getBasePositionAndOrientation(self.robot)
        else:
            frameToWorldPose = p.getLinkState(self.robot, self.frames[frame])

        return self.poseToMatrix(frameToWorldPose)

    def transformation(self, frameA, frameB):
        """Transformation matrix AtoB
        
        Arguments:
            frameA {str} -- frame A name
            frameB {str} -- frame B name
        
        Returns:
            np.matrix -- A 4x4 matrix
        """
        AtoWorld = self.frameToWorldMatrix(frameA)
        BtoWorld = self.frameToWorldMatrix(frameB)

        return np.linalg.inv(BtoWorld) * AtoWorld

    def poseToMatrix(self, pose):
        """Converts a pyBullet pose to a transformation matrix"""
        translation = pose[0]
        quaternion = pose[1]
        
        # NOTE: PyBullet quaternions are x, y, z, w
        rotation = quat2mat([quaternion[3], quaternion[0],
                             quaternion[1], quaternion[2]])

        m = np.identity(4)
        m[0:3, 0:3] = rotation
        m.T[3, 0:3] = translation

        return np.matrix(m)

    def matrixToPose(self, matrix):
        """Converts a transformation matrix to a pyBullet pose"""
        arr = np.array(matrix)
        translation = list(arr.T[3, 0:3])
        quaternion = mat2quat(arr[0:3, 0:3])

        # NOTE: PyBullet quaternions are x, y, z, w
        quaternion = [quaternion[1], quaternion[2],
                      quaternion[3], quaternion[0]]

        return translation, quaternion

    def setRobotPose(self, pos, orn):
        """Sets the robot (origin) pose
        
        Arguments:
            pos {tuple} -- (x,y,z) position
            orn {tuple} -- (x,y,z,w) quaternions
        """
        p.resetBasePositionAndOrientation(self.robot, pos, orn)

    def setBallPos(self, x, y):
        """Sets the ball position on the field"""
        if self.ball is not None:
            # Putting the ball on the ground at given position
            p.resetBasePositionAndOrientation(
                self.ball, [x, y, 0.06], p.getQuaternionFromEuler([0, 0, 0]))

            # Stopping the ball speed
            p.changeDynamics(self.ball, 0,
                             linearDamping=0, angularDamping=0.1)

    def reset(self, height=0.5, orientation='straight'):
        """Resets the robot for experiment (joints, robot position, ball position, simulator time)
        
        Keyword Arguments:
            height {float} -- height of the reset (m) (default: {0.55})
            orientation {str} -- orientation (straight, front or back) of the robot (default: {'straight'})
        """
        self.lines = []
        self.t = 0
        self.start = time.time()

        # Resets the robot position
        orn = [0, 0, 0]
        if orientation == 'front':
            orn = [0, math.pi/2, 0]
        elif orientation == 'back':
            orn = [0, -math.pi/2, 0]
        self.resetPose([0, 0, height], p.getQuaternionFromEuler(orn))

        # Reset the joints to 0
        for entry in self.joints.values():
            p.resetJointState(self.robot, entry, 0)

    def resetPose(self, pos, orn):
        """Called by reset() with the robot pose
        
        Arguments:
            pos {tuple} -- (x,y,z) position
            orn {tuple} -- (x,y,z,w) quaternions
        """
        self.setRobotPose(pos, orn)

    def getFrame(self, frame):
        """Gets the given frame
        
        Arguments:
            frame {str} -- frame name
        
        Returns:
            tuple -- (pos, orn), where pos is (x, y, z) and orn is quaternions (x, y, z, w)
        """
        jointState = p.getLinkState(self.robot, self.frames[frame])
        return (jointState[0], jointState[1])

    def getFrames(self):
        """Gets the available frames in the current robot model
        
        Returns:
            dict -- dict of str -> (pos, orientation)
        """
        frames = {}

        for name in self.frames.keys():
            jointState = p.getLinkState(self.robot, self.frames[name])
            pos = jointState[0]
            orientation = p.getEulerFromQuaternion(jointState[1])
            frames[name] = [pos, orientation]

        return frames

    def resetJoints(self, joints):
        """Reset all the joints to a given position
        
        Arguments:
            joints {dict} -- dict of joint name -> angle (float, radian)
        """
        for name in joints:
            p.resetJointState(self.robot, self.joints[name], joints[name])

    def setJoints(self, joints):
        """Set joint targets for motor control in simulation
        
        Arguments:
            joints {dict} -- dict of joint name -> angle (float, radian)
        
        Raises:
            Exception: if a joint is not found, exception is raised
        """
        for name in joints.keys():
            if name in self.joints:
                p.setJointMotorControl2(
                    self.robot, self.joints[name], p.POSITION_CONTROL, joints[name])
            else:
                raise Exception("Can't find joint %s" % name)

    def getJoints(self):
        """Get all the joints names
        
        Returns:
            list -- list of str, with joint names
        """
        return self.joints.keys()

    def getRobotMass(self):
        """Returns the robot mass

        Returns:
            float -- the robot mass (kg)
        """
        k = -1
        mass = 0
        while True:
            if k == -1 or p.getLinkState(self.robot, k) is not None:
                d = p.getDynamicsInfo(self.robot, k)
                mass += d[0]
            else:
                break
            k += 1
        return mass

    def addDebugPosition(self, position, color=None, duration=30):
        """Adds a debug position to be drawn as a line
        
        Arguments:
            position {tuple} -- (x,y,z) (m)
        
        Keyword Arguments:
            color {tuple} -- (r,g,b) (0->1) (default: {None})
            duration {float} -- line duration on screen before disapearing (default: {30})
        """
        if color is None:
            color = self.lineColors[self.currentLine % len(self.lineColors)]

        if self.currentLine >= len(self.lines):
            self.lines.append({})

        self.lines[self.currentLine]['update'] = True
        self.lines[self.currentLine]['to'] = position
        self.lines[self.currentLine]['color'] = color
        self.lines[self.currentLine]['duration'] = duration
        
        self.currentLine += 1

    def drawDebugLines(self):
        """Updates the drawing of debug lines"""
        self.currentLine = 0
        if time.time() - self.lastLinesDraw > 0.05:
            for line in self.lines:
                if 'from' in line:
                    if line['update'] == True:
                        p.addUserDebugLine(line['from'], line['to'], line['color'], 2, line['duration'])
                        line['update'] = False
                    else:
                        del line['from']
                line['from'] = line['to']

            self.lastLinesDraw = time.time()

    def contactPoints(self):
        """Gets all contact points and forces
        
        Returns:
            list -- list of entries (link_name, position in m, force in N)
        """
        result = []
        contacts = p.getContactPoints(bodyA=self.floor, bodyB=self.robot)
        for contact in contacts:
            link_index = contact[4]
            if link_index >= 0:
                link_name = (p.getJointInfo(self.robot, link_index)[12]).decode()
            else:
                link_name = 'base'
            result.append((link_name, contact[6], contact[9]))

        return result

    def autoCollisions(self):
        """Returns the total amount of N in autocollisions (not with ground)
        
        Returns:
            float -- Newtons of collisions not with ground
        """
        total = 0
        for k in range(1, p.getNumJoints(self.robot)):
            contacts = p.getContactPoints(bodyA=k)
            for contact in contacts:
                if contact[2] != self.floor:
                    total += contact[9]
        return total

    def execute(self):
        """Executes the simulaiton infinitely (blocks)"""
        while True:
            self.tick()

    def tick(self):
        """Ticks one step of simulation. If realTime is True, sleeps to compensate real time"""
        self.t += self.dt
        self.drawDebugLines()

        p.stepSimulation()
        delay = self.t - (time.time() - self.start)
        if delay > 0 and self.realTime:
            time.sleep(delay)
        