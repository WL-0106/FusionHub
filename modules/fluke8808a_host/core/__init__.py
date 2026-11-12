# -*- coding: utf-8 -*-
"""FLUKE 8808A 上位机控制软件包。
架构分层：commands(单一事实源) -> simulator/stack(协议层) -> instrument(语义接口) -> ui(界面)。
界面只调用 instrument 语义接口，不接触帧字节。
"""
