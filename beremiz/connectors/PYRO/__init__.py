#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#Copyright (C) 2007: Edouard TISSERANT and Laurent BESSARD
#
#See COPYING file for copyrights details.
#
#This library is free software; you can redistribute it and/or
#modify it under the terms of the GNU General Public
#License as published by the Free Software Foundation; either
#version 2.1 of the License, or (at your option) any later version.
#
#This library is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#General Public License for more details.
#
#You should have received a copy of the GNU General Public
#License along with this library; if not, write to the Free Software
#Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
import Pyro.core as pyro
from Pyro.errors import PyroError
import Pyro.util
import traceback
from time import sleep
import copy
import socket
service_type = '_PYRO._tcp.local.'

# this module attribute contains a list of DNS-SD (Zeroconf) service types
# supported by this connector confnode.
#
# for connectors that do not support DNS-SD, this attribute can be omitted
# or set to an empty list.

def PYRO_connector_factory(uri, confnodesroot):
    """
    This returns the connector to Pyro style PLCobject
    """
    confnodesroot.logger.write(_("Connecting to URI : %s\n")%uri)

    servicetype, location = uri.split("://")
    if location.find(service_type) != -1:
        try :
            from util.Zeroconf import Zeroconf
            r = Zeroconf()
            i=r.getServiceInfo(service_type, location)
            if i is None : raise Exception, "'%s' not found"%location
            ip = str(socket.inet_ntoa(i.getAddress()))
            port = str(i.getPort())
            newlocation = ip+':'+port
            confnodesroot.logger.write(_("'%s' is located at %s\n")%(location, newlocation))
            location = newlocation
            r.close()
        except Exception, msg:
            confnodesroot.logger.write_error(_("MDNS resolution failure for '%s'\n")%location)
            confnodesroot.logger.write_error(traceback.format_exc())
            return None
    
    # Try to get the proxy object
    try :
        RemotePLCObjectProxy = pyro.getAttrProxyForURI("PYROLOC://"+location+"/PLCObject")
    except Exception, msg:
        confnodesroot.logger.write_error(_("Connection to '%s' failed.\n")%location)
        confnodesroot.logger.write_error(traceback.format_exc())
        return None

    def PyroCatcher(func, default=None):
        """
        A function that catch a pyro exceptions, write error to logger
        and return defaul value when it happen
        """
        def catcher_func(*args,**kwargs):
            try:
                return func(*args,**kwargs)
            except Pyro.errors.ConnectionClosedError, e:
                confnodesroot.logger.write_error("Connection lost!\n")
                confnodesroot._SetConnector(None)
            except Pyro.errors.ProtocolError, e:
                confnodesroot.logger.write_error("Pyro exception: "+str(e)+"\n")
            except Exception,e:
                #confnodesroot.logger.write_error(traceback.format_exc())
                errmess = ''.join(Pyro.util.getPyroTraceback(e))
                confnodesroot.logger.write_error(errmess+"\n")
                print errmess
                confnodesroot._SetConnector(None)
            return default
        return catcher_func

    # Check connection is effective. 
    # lambda is for getattr of GetPLCstatus to happen inside catcher
    if PyroCatcher(lambda:RemotePLCObjectProxy.GetPLCstatus())() is None:
        confnodesroot.logger.write_error(_("Cannot get PLC status - connection failed.\n"))
        return None


    class PyroProxyProxy:
        """
        A proxy proxy class to handle Beremiz Pyro interface specific behavior.
        And to put pyro exception catcher in between caller and pyro proxy
        """
        def __init__(self):
            # for safe use in from debug thread, must create a copy
            self.RemotePLCObjectProxyCopy = None

        def GetPyroProxy(self):
            """
            This func returns the real Pyro Proxy.
            Use this if you musn't keep reference to it.
            """
            return RemotePLCObjectProxy

        def _PyroStartPLC(self, *args, **kwargs):
            """
            confnodesroot._connector.GetPyroProxy() is used 
            rather than RemotePLCObjectProxy because
            object is recreated meanwhile, 
            so we must not keep ref to it here
            """
            current_status, log_count = confnodesroot._connector.GetPyroProxy().GetPLCstatus()
            if current_status == "Dirty":
                """
                Some bad libs with static symbols may polute PLC
                ask runtime to suicide and come back again
                """
                confnodesroot.logger.write(_("Force runtime reload\n"))
                confnodesroot._connector.GetPyroProxy().ForceReload()
                confnodesroot._Disconnect()
                # let remote PLC time to resurect.(freeze app)
                sleep(0.5)
                confnodesroot._Connect()
            self.RemotePLCObjectProxyCopy = copy.copy(confnodesroot._connector.GetPyroProxy())
            return confnodesroot._connector.GetPyroProxy().StartPLC(*args, **kwargs)
        StartPLC = PyroCatcher(_PyroStartPLC, False)


        def _PyroGetTraceVariables(self):
            """
            for safe use in from debug thread, must use the copy
            """
            if self.RemotePLCObjectProxyCopy is None:
                self.RemotePLCObjectProxyCopy = copy.copy(confnodesroot._connector.GetPyroProxy())
            return self.RemotePLCObjectProxyCopy.GetTraceVariables()
        GetTraceVariables = PyroCatcher(_PyroGetTraceVariables,("Broken",None,None))

        def _PyroGetPLCstatus(self):
            return RemotePLCObjectProxy.GetPLCstatus()
        GetPLCstatus = PyroCatcher(_PyroGetPLCstatus, ("Broken",None))

        def _PyroRemoteExec(self, script, **kwargs):
            return RemotePLCObjectProxy.RemoteExec(script, **kwargs)
        RemoteExec = PyroCatcher(_PyroRemoteExec, (-1, "RemoteExec script failed!"))

        def __getattr__(self, attrName):
            member = self.__dict__.get(attrName, None)
            if member is None:
                def my_local_func(*args,**kwargs):
                    return RemotePLCObjectProxy.__getattr__(attrName)(*args,**kwargs)
                member = PyroCatcher(my_local_func, None)
                self.__dict__[attrName] = member
            return member

    return PyroProxyProxy()
    

