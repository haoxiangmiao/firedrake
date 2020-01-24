import itertools

from pyop2.mpi import COMM_SELF
from firedrake.preconditioners.base import PCBase
from firedrake.petsc import PETSc
from firedrake.dmhooks import get_appctx

class ASMPatchPC(PCBase):
    ''' Modified ASMPatchPC based on Colin's suggestions
    These patches are made by looping over base mesh interior DOFs
    and collecting all the DOFs on the "horizontal" faces.
    Then looping over all facet DOFs and collecting the DOFs on the
    "vertical" faces. 
    '''
    
    def initialize(self, pc):
        # Get context from pc
        _, P = pc.getOperators()
        if P.getType() == 'python':
            ctx = P.getPythonContext()
        else:
            ctx = get_appctx(pc.getDM()).appctx
        
        # Extract function space and mesh to obtain plex and indexing functions
        V = ctx['TraceSpace']
        mesh = V._mesh
        dm = mesh._plex
        section = V.dm.getDefaultSection()
        lgmap = V.dof_dset.lgmap
        
        # Obtain the codimensions to loop over from options, if present
        self.prefix = pc.getOptionsPrefix() + "pc_asm_"
        codim_list = PETSc.Options().getString(self.prefix
                                                + "codims",
                                                "0, 1")
        codim_list = [int(ii) for ii in codim_list.split(',')]
        
        # Build index sets for the patches
        ises = []
        # Loop over faces of base mesh, then edges
        for codim in codim_list:
            for f in range(*dm.getHeightStratum(codim)):
                # Only want to build patches over owned faces
                if dm.getLabelValue("pyop2_ghost", f) != -1:
                    continue
                # Collect all dofs that plex thinks live on the face or edge
                dof = section.getDof(f)
                if dof <= 0:
                    continue
                off = section.getOffset(f)
                indices = range(off, off+dof)
                # Map local indices into global indices and create the IS for PCASM
                global_index = lgmap.apply(indices)
                iset = PETSc.IS().createGeneral(global_index, comm=COMM_SELF)
                ises.append(iset)
        
        # Create new PC object as ASM type and set index sets for patches
        asmpc = PETSc.PC().create(comm=pc.comm)
        asmpc.setOperators(*pc.getOperators())
        asmpc.setType(asmpc.Type.ASM)
        asmpc.setASMLocalSubdomains(len(ises), ises)
        asmpc.setFromOptions()
        self.asmpc = asmpc
    
    def update(self, pc):
        pass

    def apply(self, pc, x, y):
        self.asmpc.apply(x, y)

    def applyTranspose(self, pc, x, y):
        self.asmpc.applyTranspose(x, y)