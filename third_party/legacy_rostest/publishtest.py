#!/usr/bin/env python
###############################################################################
# Software License Agreement (BSD License)
#
# Copyright (c) 2016, Kentaro Wada.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###############################################################################
"""
Integration test node that subscribes to any topic and verifies
there is at least one message publishing of the topic.
below parameters must be set:

<test name="publishtest"
      test-name="publishtest"
      pkg="rostest" type="publishtest">
  <rosparam>
    topics:
      - name: a topic name
        timeout: timeout for the topic
      - name: another topic name
        timeout: timeout for the topic
  </rosparam>
</test>

Author: Kentaro Wada <www.kentaro.wada@gmail.com>
"""

# pylint: disable=bad-super-call,consider-using-f-string
# pylint: disable=line-too-long

import sys
import time
import unittest

import rospy

import third_party.legacy_rostest as rostest

PKG = 'rostest'
NAME = 'publishtest'


class PublishChecker(object):

    def __init__(self, topic_name, timeout, negative):
        self.topic_name = topic_name
        self.negative = negative
        self.deadline = rospy.Time.now() + rospy.Duration(timeout)
        self.msg = None
        self.sub = rospy.Subscriber(topic_name, rospy.AnyMsg, self._callback)

    def _callback(self, msg):
        self.msg = msg

    def assert_published(self):
        if self.msg:
            return not self.negative
        if rospy.Time.now() > self.deadline:
            return self.negative
        return None


class PublishTest(unittest.TestCase):

    def __init__(self, *args):
        super(self.__class__, self).__init__(*args)
        rospy.init_node(NAME)
        # scrape rosparam
        self.topics = []
        params = rospy.get_param('~topics', [])
        for param in params:
            if 'name' not in param:
                self.fail(
                    "'name' field in rosparam is required but not specified.")
            topic = {'timeout': 10, 'negative': False}
            topic.update(param)
            self.topics.append(topic)
        # check if there is at least one topic
        if not self.topics:
            self.fail('No topic is specified in rosparam.')

    def test_publish(self):
        """Test topics are published and messages come"""
        use_sim_time = rospy.get_param('/use_sim_time', False)
        t_start = time.time()
        while not rospy.is_shutdown() and \
                use_sim_time and (rospy.Time.now() == rospy.Time(0)):
            rospy.logwarn_throttle(
                1,
                '/use_sim_time is specified and rostime is 0, /clock is published?'
            )
            if time.time() - t_start > 10:
                self.fail('Timed out (10s) of /clock publication.')
            # must use time.sleep because /clock isn't yet published, so rospy.sleep hangs.
            time.sleep(0.1)
        # subscribe topics
        checkers = []
        for topic in self.topics:
            topic_name = topic['name']
            timeout = topic['timeout']
            negative = topic['negative']
            print('Waiting [%s] for [%d] seconds with negative [%s]' %
                  (topic_name, timeout, negative))
            checkers.append(PublishChecker(topic_name, timeout, negative))
        # assert
        finished_topics = []
        while not rospy.is_shutdown():
            if len(self.topics) == len(finished_topics):
                break
            for checker in checkers:
                if checker.topic_name in finished_topics:
                    continue  # skip topic testing has finished
                ret = checker.assert_published()
                if ret is None:
                    continue  # skip if there is no test result
                finished_topics.append(checker.topic_name)
                if checker.negative:
                    assert ret, 'Topic [%s] is published' % (checker.topic_name)
                else:
                    assert ret, 'Topic [%s] is not published' % (
                        checker.topic_name)
            rospy.sleep(0.01)


if __name__ == '__main__':
    rostest.run(PKG, NAME, PublishTest, sys.argv)
