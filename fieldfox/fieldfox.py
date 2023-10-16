#!/usr/bin/env python3

import pyvisa
import sys
import time
import skrf
import numpy as np
import click

class UndefinedPropertyException(Exception):
    def __init__(self, parent, path):
        self.path = path

class SCPIError(Exception):
    def __init__(self, error_code, error_str):
        self.error_code = error_code
        self.error_str = error_str
        
class SCPICmd:
    def read(self):
        #print(f"Fetching {self.__scpi_name__}")
        r = self.device.query(self.__scpi_name__)
        self.device.check_err()
        return r
        
    def write(self, val):
        print(f"Set: {self.__scpi_name__} {val}")
        self.device.write(f"{self.__scpi_name__} {val}")
        self.device.check_err()

    def __getattr__(self, name):
        if name in self.__scpi_children__:
            c = self.__scpi_children__[name](self.device)
            if c.__scpi_terminal__:
                return c.read()
            else:
                return c

        raise UndefinedPropertyException(name)
        
    def __setattr__(self, name, val):
        if name in self.__scpi_children__:
            return self.__scpi_children__[name](self.device).write(val)
            
        raise UndefinedPropertyException(self.__scpi_name__, name)
        
    def __init__(self, device):
        self.__dict__['device'] = device
            

def scpi_create(device, name, children):
    if v is not None:
        return SCPICmdGrp(self, k, v)
    else:
        return SCPICmd(self, k)

def scpi_create_classes(device, parent, children):
    if children == None:
        parent.__scpi_terminal__ = True
        return

    parent.__scpi_terminal__ = False
    parent.__scpi_children__ = dict()
    
    for k, v in children.items():
        typename = parent.__name__ + "_" + k if parent != device else "SCPICmd_" + k
        scpi_name = parent.__scpi_name__ + ":" + k if parent.__scpi_name__ != "" else k
        
        t = type(typename, (SCPICmd, ), {
            #"__scpi_name__": parent.__scpi_name__ + ":" + k[0:4].upper() if parent.__scpi_name__ != "" else k[0:4].upper()
            "__scpi_name__": scpi_name
        })

        device.__scpi_classes__[scpi_name] = t
        parent.__scpi_children__[k] = t
        
        #setattr(parent, k, t(None))

        scpi_create_classes(device, t, v)
    
class SCPIMeta(type):
    def __new__(cls, name, bases, dct):
        retval = super().__new__(cls, name, bases, dct)

        retval.__scpi_classes__ = dict()
        retval.__scpi_name__ = ""
        
        scpi_create_classes(retval, retval, retval.__scpi_cmd__)
        
        return retval
    
class SCPIDevice(metaclass=SCPIMeta):
    __scpi_cmd__ = {}

    def __getattr__(self, name):
        if name in self.__scpi_children__:
            return self.__scpi_children__[name](self)
        return None
    
    @property
    def fqcn(self):
        return ""    
                
class FieldFox(SCPIDevice):
    window_trace_dict = {
        'y': {
            'scale': {
                'auto': None,
                'bottom': None,
                'pdivision': None,
                'rlevel': None,
                'rposition': None,
                'top': None
            }
        }
    }
    
    __scpi_cmd__ = {
        'sense':
        {
            'sweep':
            {
                'points': None
            },
            'freq':
            {
                'start': None,
                'stop': None,
                'span': None,
                'center': None,
                'data': None
            },
            'band':
            {
                'res' : None,
                'vid' : None
            },
            
            'bwid': None,
            'average': { 'count': None }
        },
        'display':
        {
            'window':
            {
                'trace': window_trace_dict,
                'trace1': window_trace_dict,
                'trace2': window_trace_dict,
                'trace3': window_trace_dict,
                'trace4': window_trace_dict,
                'split': None,
                'select': None
            }
        },
        'calculate':
        {
            'parameter1': { 'define': None },
            'parameter2': { 'define': None },
            'parameter3': { 'define': None },
            'parameter4': { 'define': None },
        },
        'source':
        {
            'power': None
        }
        
    }
    
    def __init__(self, rm, ipaddr):
        self.rm = rm
        self.ipaddr = ipaddr
        self.reconnect()

        
        self.write("*CLS")
        (self.mfg, self.model, self.serial, self.fw) = self.query("*IDN").split(",")
        print(f"Model: {self.model}")

    def reconnect(self):
        self.res = self.rm.open_resource(f"TCPIP0::{self.ipaddr}::inst0::INSTR")
        self.res.timeout = 20000
        
    def write(self, s):
        self.res.write(s)

    def read(self):
        return self.res.read()

    def query(self, s):
        self.res.write(f"{s}?")
        return self.res.read()

    def trigger(self):
        self.write("INIT:CONT 0")
        self.write("INIT")

    def wait_long(self):
        self.write(f"*CLS")
        self.write(f"*OPC")

        while True:
            try:
                self.write(f"*ESR?")
            except pyvisa.errors.VisaIOError:
                print("VISA Error Query -- probably timeout")
                time.sleep(1)
                self.reconnect()
                continue
            
            try:
                r = int(self.read())

                if r & 1:
                    break
                time.sleep(1)
            except pyvisa.errors.VisaIOError:
                print("VISA Error Read -- probably timeout")
                time.sleep(1)
                self.reconnect()
                continue

            
    def reset(self):
        self.write("*RST")

    def wait(self):
        self.write("*WAI")
        assert(self.opc() == 1)

    def na_mode(self):
        self.write('INST:SEL "NA"')
        self.opc()
        self.mode = "NA"

    def sa_mode(self):
        self.write('INST:SEL "SA"')
        self.opc()
        self.mode = "SA"

        
    def opc(self):
        self.write('*OPC?')
        return int(self.read())
        
    def check_err(self):
        err = []
        
        es = self.query("SYST:ERR")

        elist = es.split(',')
        
        if int(elist[0]) == 0:
            return 0
        
        print(f"Error detected: {elist}")

        raise SCPIError(elist[0], elist[1])

    def read_real_array(self):
        return np.asarray(list(map(float,self.read().strip().split(","))))

    def read_complex_array(self):
        data = self.read_real_array().reshape((-1,2))
        return np.vectorize(complex)(data[...,0], data[...,1])
        
    
    @property
    def freq_data(self):
        self.write("SENS:FREQ:DATA?")
        return self.read_real_array()
        
    def trace_data(self, n):
        if self.mode == "NA":
            self.write(f"CALC:PAR{n}:SEL")
            self.write("FORM:DATA ASC,0")
            self.check_err()
            self.write("CALC:DATA:SDATA?")

            return self.read_complex_array()
        elif self.mode == "SA":
            self.write(f"TRACE:DATA?")

            return self.read_real_array()
            

