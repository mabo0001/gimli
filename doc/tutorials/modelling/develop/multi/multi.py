#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pygimli as pg
import pybert as pb
import numpy as np

from multi_darcy_flow import darcyFlow
from multi_advection import calcSaturation
from multi_ert import simulateERTData, showERTData

from multiprocessing import Process, Queue


class WorkSpace():
    pass

class MulitFOP(pg.ModellingBase):
    def __init__(self, paraMesh=None, tMax=5000, tSteps=10, peclet=500, verbose=False):
        pg.ModellingBase.__init__(self, verbose=verbose)

        self.tSteps = tSteps
        if paraMesh:
            self.setMesh(paraMesh)
            self.createRefinedForwardMesh(refine=False, pRefine=False)
        else:
            self.regionManager().setParameterCount(3)
        
        self.setStartModel([1e-7, 0.01, 0.001])
            
        self.ws = WorkSpace()
        self.timesAdvection = np.linspace(1, tMax, tSteps)
        self.peclet = peclet
        self._J = pg.RMatrix()
        self.setJacobian(self._J)   
        self.iter = 0
        
    def createJacobian(self, model):
        self.iter += 1  
        print("Create Jacobian for", str(model))
        nModel = len(model)
        resp = self.response(model)
        nData = len(resp)
        
        self._J.resize(nData, nModel)
        self._J *= 0.
        
        respChange = pg.RMatrix(nModel, nData)
        dModel = pg.RVector(len(model))

        fak = 1.05
        q = Queue()
         
        pg.tic()
        for i in range(nModel):
            p = Process(target=self.createResponseProc, args=(model, fak, i, q))
            p.start()
        p.join()
        pg.toc()
        
        for i in range(nModel):
            Imodel, respChange, dModel = q.get()
            dData = respChange - resp
            self._J.setCol(Imodel, dData/dModel)
    
    def createResponseProc(self, model, fak, i, q):
        print("proc:", i)
        modelChange = pg.RVector(model)
        modelChange[i] *= fak
                
        meshIn = pg.Mesh(self.mesh())
        meshIn.setCellAttributes(modelChange[meshIn.cellMarker()])
                
        mesh, vel, p, k = darcyFlow(meshIn, verbose=0)
        sat = calcSaturation(mesh, vel.T, self.timesAdvection, 
                             injectPos=[2., -2.], peclet=self.peclet, verbose=0)
        
        sampleTime = [0, self.tSteps/2, self.tSteps-1]
        meshERT, dataERT, res, rhoa, err = simulateERTData(sat[sampleTime], mesh, verbose=0)

        q.put([i, rhoa.flatten(), modelChange[i]-model[i]])
        #return rhoa.flatten(), modelChange[i]-model[i]
                
                
    def response(self, par):
        ws = self.ws
        print('create response for: ' + str(par))
        
        model = par

        if self.mesh():
            self.mapModel(model)
            model = self.mesh()
        
        
        print(".. darcy step")
        ws.mesh, ws.vel, ws.p, ws.k = darcyFlow(model, verbose=0)
    
        #pg.show(ws.mesh, ws.k, label='Permeabilty iter:' + str(self.iter))
        #pg.wait()
  
        print(".. advection step")
        ws.saturation = calcSaturation(ws.mesh, ws.vel.T,
                                       self.timesAdvection, 
                                       injectPos=[2., -2.],
                                       peclet=self.peclet, verbose=0)
        
        print(".. dc step")
        sampleTime = [0, self.tSteps/2, self.tSteps-1]
        ws.meshERT, ws.dataERT, ws.res, ws.rhoa, ws.err = simulateERTData(ws.saturation[sampleTime], ws.mesh, verbose=0)

        return ws.rhoa.flatten()
    
    
def test(model, tMax=5000, tSteps=40, peclet=50000):
    paraMesh = pg.createGrid(x=[0, 10], y=[-5, -3.5, -0.5, 0])
    
    fop = MulitFOP(paraMesh, tMax=tMax, tSteps=tSteps, peclet=peclet, verbose=1)
    
    ert = fop.response(model)

    ws = fop.ws
    mesh = ws.mesh
    ax, _ = pg.show(mesh)
    pg.show(mesh, fop.ws.p, label='Pressure in ??', axes=ax)
    ax, _ = pg.show(mesh)
    pg.show(mesh, fop.ws.k, label='Permeabilty in ??', axes=ax)
    
    ax, _ = pg.show(mesh)
    pg.show(mesh, np.sqrt(fop.ws.vel[0]**2+fop.ws.vel[1]**2), label='velocity in m/s', axes=ax)
    pg.show(mesh, fop.ws.vel, axes=ax)

    pg.show(mesh, fop.ws.saturation[-1]+1e-3, label='brine saturation')
    pg.show(ws.meshERT, fop.ws.res[-1], label='resistivity in Ohm m')

    showERTData(fop.ws.dataERT, fop.ws.rhoa.flatten())
    
    pg.wait()
    
if __name__ == '__main__':
    
    #test(model=[0.0001, 0.01, 1e-7], tMax=5000, tSteps=10, peclet=500000)
    
    fop = MulitFOP(verbose=1, tMax=5000, tSteps=10, peclet=500000)
    
    rhoa = fop.response([0.001, 0.01, 1e-7]); np.save('rhoa', rhoa)
    err = fop.ws.err.flatten()
    rand = pg.RVector(len(rhoa));  pg.randn(rand)
    rhoa *= (1.0 + rand * err)

    ##### create paramesh and startmodel
    paraMesh = pg.createGrid(x=[0, 10], y=[-5, -3.5, -0.5, 0])
    paraMesh.cell(0).setMarker(0) # bottom
    paraMesh.cell(1).setMarker(1) # center
    paraMesh.cell(2).setMarker(2) # top
    paraMesh = paraMesh.createH2()
    
    fop.setMesh(paraMesh)
    fop.regionManager().region(0).setSingle(True)
    fop.regionManager().region(2).setSingle(True)
    fop.createRefinedForwardMesh(refine=False, pRefine=False)
    
    paraDomain = fop.regionManager().paraDomain()
    
    startModel = pg.RVector(fop.regionManager().parameterCount(), 0.01) # else
    startModel[0] = 0.001 # bottom
    startModel[-1] = 1e-7 # top
    fop.setStartModel(startModel) 
    
    
    rhoa2 = fop.response(startModel)
    
    print('norm: ', np.linalg.norm(np.log10(rhoa)-np.log10(rhoa2), ord=2))
    print('rms: ' , pg.rms(np.log10(rhoa)-np.log10(rhoa2)))
    print('chi: ' , pg.rms((np.log10(rhoa)-np.log10(rhoa2))/err))
    print('chi²(lin): ' , pg.utils.chi2(rhoa, rhoa2, err))
    print('chi²(log): ' , pg.utils.chi2(rhoa, rhoa2, err, pg.RTransLog()))
      
    pg.wait()
    
    
    pg.show(paraDomain, paraDomain.cellMarker())        
    pg.show(paraDomain, startModel[paraDomain.cellMarker()], label='Permeabilty')    
    #pg.wait()
    
    inv = pg.RInversion(rhoa, fop, verbose=1, dosave=1)
    
     
    tD = pg.RTransLog()
    tM = pg.RTransLog()
    inv.setTransData(tD)
    inv.setTransModel(tM)
    
    inv.setRelativeError(err)
    #inv.setLambda(0)
    inv.setLineSearch(True)
    inv.setLambda(1e-4)
    inv.setMarquardtScheme(0.5)
    
    coeff = inv.run()
    print(coeff)

# actual inversion run yielding coefficient model



pg.wait()

