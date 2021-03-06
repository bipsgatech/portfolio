from math import pi
from torihunter._arrayops import swap_modes, so2_generator, so2_coefficients
from torihunter.discretization import rediscretize
from torihunter.generate import random_initial_condition
from scipy.fft import rfft, irfft
from scipy.linalg import block_diag
from mpl_toolkits.axes_grid1 import make_axes_locatable
import copy
import os
import sys
import warnings
import numpy as np
import matplotlib.pyplot as plt
warnings.simplefilter(action='ignore', category=FutureWarning)
import h5py
warnings.resetwarnings()

__all__ = ['Torus', 'RelativeTorus', 'ShiftReflectionTorus', 'AntisymmetricTorus', 'EquilibriumTorus']


class Torus:
    """ Object that represents invariant 2-torus solution of the Kuramoto-Sivashinsky equation.

    Parameters
    ----------

    state : ndarray(dtype=float, ndim=2)
        Array which contains one of the following: velocity field,
        spatial Fourier modes, or spatiotemporal Fourier modes.
        If None then a randomly generated set of spatiotemporal modes
        will be produced.
    statetype : str
        Which basis the array 'state' is currently in. Takes values
        'field', 's_modes', 'modes'. Needs to reflect the current basis.
    T : float
        The temporal period.
    L : float
        The spatial period.
    S : float
        The spatial shift for doubly-periodic orbits with continuous translation symmetry.
        S represents rotation/translation such that S = S mod L
    **kwargs :
    N : int
        The lattice size in the temporal dimension.
    M : int
        The lattice size in the spatial dimension.

    Raises
    ----------
    ValueError :
        If 'state' is not a NumPy array

    See Also
    --------


    Notes
    -----
    The 'state' is ordered such that when in the physical basis, the last row corresponds to 't=0'. This
    results in an extra negative sign when computing time derivatives. This convention was chosen
    because it is conventional to display positive time as 'up'. This convention prevents errors
    due to flipping fields up and down. The spatial shift parameter only applies to RelativeTorus
    and RelativeEquilibriumTorus subclasses. Its inclusion in the base class is again a convention
    for exporting and importing data. If no state is None then a randomly generated state will be
    provided. It's dimensions will provide on the spatial and temporal periods unless provided
    as keyword arguments {N, M}.


    Examples
    --------
    """

    def __init__(self, state=None, statetype='modes', T=0., L=0., S=0., **kwargs):
        try:
            if state is not None:
                shp = state.shape
                self.state = state
                self.statetype = statetype
                if statetype == 'modes':
                    # This separate behavior is for Antisymmetric and ShiftReflection Tori;
                    # This avoids having to define subclass method with repeated code.
                    self.N, self.M = shp[0] + 1, shp[1] + 2
                elif statetype == 'field':
                    self.N, self.M = shp
                elif statetype == 's_modes':
                    self.N, self.M = shp[0], shp[1] + 2

                self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
                self.T, self.L = T, L
            else:
                self.statetype = 'modes'
                random_initial_condition(T, L, **kwargs)
        except ValueError:
            print('Incompatible type provided for field or modes: 2-D NumPy arrays only')
        self.mode_shape = (self.N-1, self.M-2)
        # For uniform save format
        self.S = S

    def __copy__(self):
        return self.__class__(state=self.state, T=self.T, L=self.L, S=self.S)

    def __add__(self, other):
        return self.__class__(state=(self.state + other.state),
                              T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __radd__(self, other):
        return self.__class__(state=(self.state + other.state),
                              T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __sub__(self, other):
        return self.__class__(state=(self.state-other.state),  T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __rsub__(self, other):
        return self.__class__(state=(other.state - self.state), T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __mul__(self, num):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to multiply by.

        Notes
        -----
        This is not state-wise multiplication because that it more complicated and depends on symmetry type.
        Current implementation makes it so no checks of the type of num need to be made.
        """
        return self.__class__(state=num*self.state,  T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __rmul__(self, num):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to multiply by.

        Notes
        -----
        This is not state-wise multiplication because that it more complicated and depends on symmetry type.
        Current implementation makes it so no checks of the type of num need to be made.
        """
        return self.__class__(state=num*self.state,  T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __truediv__(self, num):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to division by.

        Notes
        -----
        State-wise division is ill-defined because of division by 0.
        """
        return self.__class__(state=self.state / num, T=self.T, L=self.L, S=self.S, statetype=self.statetype)

    def __floordiv__(self, num):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to renormalize by.

        Notes
        -----
        This renormalizes the physical field such that the absolute value of the max/min takes on a new value
        of (1.0 / num).

        Examples
        --------
        >>> renormalized_torus = self // (1.0/2.0)
        >>> print(np.max(np.abs(renormalized_torus.state.ravel())))
        2.0
        """
        field = self.convert(to='field').state
        state = field / (num * np.max(np.abs(field.ravel())))
        return self.__class__(state=state, statetype='field', T=self.T, L=self.L, S=self.S)

    def __repr__(self):
        return self.__class__.__name__ + "()"

    def __getattr__(self, attr):
        # Only called if self.attr is not found.
        try:
            if str(attr) in ['T', 'L', 'S']:
                return 0.0
            elif str(attr) == 'state':
                return None
            else:
                error_message = ' '.join([self.__class__.__name__, 'has no attribute called \' {} \''.format(attr)])
                raise AttributeError(error_message)
        except ValueError:
            print('Attribute is not of readable type')

    def state_vector(self):
        """ Vector which completely specifies the Torus """
        return np.concatenate((self.state.reshape(-1, 1), [[float(self.T)]], [[float(self.L)]]), axis=0)

    def check_if_equilibrium_or_zero(self):
        """ Check whether the Torus converged to an equilibrium or close-to-zero solution """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        zero_check = np.linalg.norm(self.convert(to='field').state.ravel())

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if zero_check < 10**-8:
            return self.__class__(state=np.zeros([self.N, self.M]),
                                  statetype='field', T=self.T, L=self.L, S=self.S), False

        # Equilibrium is defined by having no temporal variation, i.e. time derivative is a uniformly zero.
        if self.__class__.__name__ != 'EquilibriumTorus':
            # Calculate the time derivative
            equilibrium_modes = self.dt().state
            # Equilibrium have non-zero zeroth modes in time, exclude these from the norm.
            equilibrium_check = np.linalg.norm(equilibrium_modes[1:, :])
            # See if the norm is less than a threshold value.
            if equilibrium_check < 10**-8:
                return EquilibriumTorus(state=equilibrium_modes, T=self.T, L=self.L, S=self.S), False
            else:
                return self, True
        else:
            return self, True

    def convert(self, inplace=False, to='modes'):
        """ Convert current state to a different basis.

        This instance method is just a wrapper for different
        Fourier transforms. It's purpose is to remove the
        need for the user to keep track of the statetype by hand.
        This should be used as opposed to Fourier transforms.

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the conversion "in place" or not.
        to : str
            One of the following: 'field', 's_modes', 'modes'. Specifies
            the basis which the torus will be converted to. \

        Raises
        ----------

        ValueError
            Raised if the provided basis is unrecognizable.

        Returns
        ----------

        converted_torus : Torus or Torus subclass instance
            The class instance in the new basis.
        """
        if to == 'field':
            if self.statetype == 's_modes':
                converted_torus = self.space_ifft()
            elif self.statetype == 'modes':
                converted_torus = self.spacetime_ifft()
            else:
                converted_torus = self
        elif to == 's_modes':
            if self.statetype == 'field':
                converted_torus = self.space_fft()
            elif self.statetype == 'modes':
                converted_torus = self.time_ifft()
            else:
                converted_torus = self
        elif to == 'modes':
            if self.statetype == 's_modes':
                converted_torus = self.time_fft()
            elif self.statetype == 'field':
                converted_torus = self.spacetime_fft()
            else:
                converted_torus = self
        else:
            raise ValueError('Trying to convert to unrecognizable state type.')

        if inplace:
            self.state = converted_torus.state
            self.statetype = to
            return self
        else:
            return converted_torus

    def dot(self, other):
        """ Return the L_2 inner product of two 2-tori

        Returns
        -------
        float :
            The value of self * other via L_2 inner product.
        """
        return float(np.dot(self.state.reshape(1, -1), other.state.reshape(-1, 1)))

    def dt(self, order=1):
        """ A time derivative of the current state.

        Parameters
        ----------
        order : int
            The order of the derivative.

        Returns
        ----------
        torus_dtn : Torus or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """

        wj = self.frequency_vector()
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(order=order)
        # The Nyquist frequency is never included, this is how time frequency modes are ordered.
        wjn_vec = np.concatenate(([[0]], c1*wj**order, c2*wj**order), axis=0)
        # Elementwise product of modes with time frequencies is the spectral derivative.
        dtn_modes = np.multiply(self.state, np.tile(wjn_vec, (1, self.state.shape[1])))
        # If the order of the derivative is odd, then imaginary component and real components switch.
        if np.mod(order, 2):
            dtn_modes = swap_modes(dtn_modes, dimension='time')

        torus_dtn = self.__class__(state=dtn_modes, statetype='modes', T=self.T, L=self.L, S=self.S)
        return torus_dtn

    def dt_matrix(self, order=1):
        """ The time derivative matrix operator for the current state.

        Parameters
        ----------
        order : int
            The order of the derivative.

        Returns
        ----------
        wk_matrix : matrix
            The operator whose matrix-vector product with spatiotemporal
            Fourier modes is equal to the time derivative. Used in
            the construction of the Jacobian operator.

        Notes
        -----
        Before the kronecker product, the matrix dt_n_matrix is the operator which would correctly take the
        time derivative of a single set of N-1 temporal modes. Because we have space as an extra dimension,
        we need a number of copies of dt_n_matrix equal to the number of spatial frequencies.
        """
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        dt_n_matrix = np.kron(so2_generator(order=order), np.diag(self.frequency_vector().ravel()**order))
        # Zeroth frequency was not included in frequency vector.
        dt_n_matrix = block_diag([[0]], dt_n_matrix)
        # Take kronecker product to account for the number of spatial modes.
        spacetime_dtn = np.kron(dt_n_matrix, np.eye(self.mode_shape[1]))
        return spacetime_dtn

    def dx(self, order=1):
        """ A spatial derivative of the current state.

        Parameters
        ----------
        order : int
            The order of the derivative.

        Returns
        ----------
        torus_dxn : Torus or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """

        qkn = self.wave_vector()**order
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(order=order)
        # Create elementwise spatial frequency matrix
        elementwise_dxn = np.tile(np.concatenate((c1*qkn, c2*qkn), axis=1), (self.N-1, 1))
        # Elementwise multiplication of modes with frequencies, this is the derivative.
        dxn_modes = np.multiply(elementwise_dxn, self.convert(to='modes').state)

        # If the order of the differentiation is odd, need to swap imaginary and real components.
        if np.mod(order, 2):
            dxn_modes = swap_modes(dxn_modes, dimension='space')
        torus_dxn = self.__class__(state=dxn_modes, statetype='modes', T=self.T, L=self.L, S=self.S)
        return torus_dxn

    def dx_matrix(self, order=1, **kwargs):
        """ The space derivative matrix operator for the current state.

        Parameters
        ----------
        order : int
            The order of the derivative.
        **kwargs :
            statetype: str
            The basis the current state is in, can be 'modes', 's_modes'
            or 'field'. (spatiotemporal modes, spatial_modes, or velocity field, respectively).
        Returns
        ----------
        spacetime_dxn : matrix
            The operator whose matrix-vector product with spatiotemporal
            Fourier modes is equal to the time derivative. Used in
            the construction of the Jacobian operator.

        Notes
        -----
        Before the kronecker product, the matrix space_dxn is the operator which would correctly take the
        time derivative of a set of M-2 spatial modes (technically M/2-1 real + M/2-1 imaginary components).
        Because we have time as an extra dimension, we need a number of copies of
        space_dxn equal to the number of temporal frequencies. If in the spatial mode basis, this is the
        number of time points instead.
        """

        statetype = kwargs.get('statetype', self.statetype)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        space_dxn = np.kron(so2_generator(order=order), np.diag(self.wave_vector().ravel()**order))
        if statetype == 'modes':
            spacetime_dxn = np.kron(np.eye(self.mode_shape[0]), space_dxn)
        else:
            spacetime_dxn = np.kron(np.eye(self.N), space_dxn)

        return spacetime_dxn

    def elementwise_dt(self):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered temporal frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a time derivative.


        Returns
        ----------
        matrix
            Matrix of temporal frequencies
        """
        wj = self.frequency_vector()
        wj_vec = np.concatenate(([[0]], wj, -1.0*wj), axis=0)
        return np.tile(wj_vec, (1, self.state.shape[1]))

    def elementwise_dx(self):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered spatial frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a spatial derivative.

        Returns
        ----------
        matrix
            Matrix of spatial frequencies
        """
        qk = self.wave_vector()
        qk_vec = np.concatenate((qk, -qk), axis=1)
        return np.tile(qk_vec, (self.N-1, 1))

    def frequency_vector(self):
        """
        Returns
        -------
        ndarray
            Temporal frequency array of shape {n, 1}

        Notes
        -----
        Extra factor of '-1' because of how the state is ordered; see __init__ for
        more details.

        """
        return (-1.0 * (2 * pi * self.N / self.T) * np.fft.fftfreq(self.N)[1:self.n+1]).reshape(-1, 1)

    def from_fundamental_domain(self):
        """ This is a placeholder for the subclasses """
        return self

    def increment(self, other, stepsize=1):
        """ Add optimization correction  to current state

        Parameters
        ----------
        other : Torus
            Represents the values to increment by.
        stepsize : float
            Multiplicative factor which decides the step length of the correction.

        Returns
        -------
        Torus
            New Torus which results from adding an optimization correction to self.
        """
        return self.__class__(state=self.state+stepsize*other.state,
                              T=self.T+stepsize*other.T, L=self.L+stepsize*other.L)

    def jac(self, fixedparams=(False, False)):
        """ Jacobian matrix evaluated at the current state.

        Parameters
        ----------
        fixedparams : tuple of bools
            Determines whether to include period and spatial period
            as variables.

        Returns
        -------
        jac_ : matrix ((N-1)*(M-2), (N-1)*(M-2) + n_params)
            Jacobian matrix of the KSe where n_params = 2 - sum(fixedparams)

        """
        # The Jacobian components for the spatiotemporal Fourier modes
        jac_ = self.jac_lin() + self.jac_nonlin()

        # If period is not fixed, need to include dF/dT for changes to period.
        if not fixedparams[0]:
            # Derivative with respect to T of the time derivative term, equal to -1/T u_t
            dt = swap_modes(np.multiply(self.elementwise_dt(), self.state), dimension='time')
            dfdt = (-1.0 / self.T)*dt.reshape(1, -1)
            jac_ = np.concatenate((jac_, dfdt.reshape(-1, 1)), axis=1)

        # If period is not fixed, need to include dF/dL for changes to period.
        if not fixedparams[1]:
            field_torus = self.convert(to='field')
            qk_matrix = self.elementwise_dx()

            # The derivative with respect to L of the linear component. Equal to -2/L u_xx - 4/L u_xxxx
            d2x = np.multiply(-1.0 * qk_matrix**2, self.state)
            d4x = np.multiply(qk_matrix**4, self.state)
            dfdl_linear = (-2.0/self.L) * d2x + (-4.0/self.L) * d4x

            # The derivative with respect to L of the nonlinear component. Equal to -1/L (0.5 (u^2)_x)
            dfdl_nonlinear = (- 1.0 / self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear

            # Augment the Jacobian with the partial derivative
            jac_ = np.concatenate((jac_, dfdl.reshape(-1, 1)), axis=1)

        return jac_

    def jac_lin(self):
        """ The linear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation"""
        return self.dt_matrix() + self.dx_matrix(order=2) + self.dx_matrix(order=4)

    def jac_nonlin(self):
        """ The nonlinear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation

        Returns
        -------
        nonlinear_dx : matrix
            Matrix which represents the nonlinear component of the Jacobian. The derivative of
            the pseudospectral term, which is
            (D/DU) 1/2 d_x (u .* u) = (D/DU) 1/2 d_x F (diag(F^-1 u)^2)  = d_x F( diag(F^-1 u) F^-1).
            See
            Chu, K.T. A direct matrix method for computing analytical Jacobians of discretized nonlinear
            integro-differential equations. J. Comp. Phys. 2009
            for details.
        """
        nonlinear = np.dot(np.diag(self.spacetime_ifft().state.ravel()), self.spacetime_ifft_matrix())
        nonlinear_dx = np.dot(self.time_fft_matrix(),
                              np.dot(self.dx_matrix(statetype='s_modes'),
                                     np.dot(self.space_fft_matrix(), nonlinear)))
        return nonlinear_dx

    def l2_distance(self, other):
        """ L_2 norm between two sets of spatiotemporal states"""
        return np.linalg.norm(self.state.ravel() - other.state.ravel())

    def matvec(self, other, fixedparams=(False, False), preconditioning=True):
        """ Matrix-vector product of a vector with the Jacobian of the current state.

        Parameters
        ----------
        other : Torus
            Torus instance whose state represents the vector in the matrix-vector multiplication.
        fixedparams : tuple of bool
            Determines whether to include period and spatial period
            as variables.
        preconditioning : bool
            Whether or not to apply (left) preconditioning P (Ax)

        Returns
        -------
        Torus
            Torus whose state and other parameters result from the matrix-vector product.

        Notes
        -----
        Equivalent to computation of v_t + v_xx + v_xxxx + d_x (u .* v)

        """
        # Create elementwise frequency matrices for the derivatives
        wj_matrix = self.elementwise_dt()
        qk_matrix = self.elementwise_dx()
        elementwise_qk2 = -1.0*qk_matrix**2
        elementwise_qk4 = qk_matrix**4

        # Compute the derivatives
        dt = swap_modes(np.multiply(wj_matrix, other.state), dimension='time')
        d2x = np.multiply(elementwise_qk2, other.state)
        d4x = np.multiply(elementwise_qk4, other.state)

        # Add up linear derivatives
        linear_term = dt + d2x + d4x
        linear_torus = self.__class__(state=linear_term, statetype='modes', T=self.T, L=self.L)

        # Compute nonlinear term
        field_torus = self.convert(to='field')
        matvec_torus = linear_torus + 2 * field_torus.pseudospectral(other, qk_matrix)
        if not fixedparams[0]:
            # Compute the product of the partial derivative with respect to T with the vector's value of T.
            # This is typically an incremental value dT.
            matvec_torus.state = matvec_torus.state + other.T * (-1.0 / self.T) * dt

        if not fixedparams[1]:
            # Compute the product of the partial derivative with respect to L with the vector's value of L.
            # This is typically an incremental value dL.
            d2x_self = np.multiply(elementwise_qk2, self.state)
            d4x_self = np.multiply(elementwise_qk4, self.state)
            dfdl_linear = (-2.0/self.L)*d2x_self + (-4.0/self.L)*d4x_self
            dfdl_nonlinear = (-1.0/self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear
            matvec_torus.state = matvec_torus.state + other.L*dfdl

        # This is equivalent to LEFT preconditioning.
        if preconditioning:
            p_matrix = 1.0 / (np.abs(wj_matrix) + qk_matrix**2 + qk_matrix**4)
            matvec_torus.state = np.multiply(matvec_torus.state, p_matrix)

        return matvec_torus

    def mode_padding(self, size, dimension='space'):
        """ Increase the size of the discretization via zero-padding

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            larger than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be padded.

        Returns
        -------
        Torus
            Torus instance with larger discretization.
        """

        if dimension == 'time':
            # Split into real and imaginary components, pad separately.
            first_half = self.state[:-self.n, :]
            second_half = self.state[-self.n:, :]
            padding_number = int((size-self.N) // 2)
            padding = np.zeros([padding_number, self.state.shape[1]])
            padded_modes = np.concatenate((first_half, padding, second_half, padding), axis=0)
        else:
            # Split into real and imaginary components, pad separately.
            first_half = self.state[:, :-self.m]
            second_half = self.state[:, -self.m:]
            padding_number = int((size-self.M) // 2)
            padding = np.zeros([self.state.shape[0], padding_number])
            padded_modes = np.concatenate((first_half, padding, second_half, padding), axis=1)
        return self.__class__(state=padded_modes, statetype=self.statetype, T=self.T, L=self.L, S=self.S)

    def mode_truncation(self, size, dimension='space'):
        """ Decrease the size of the discretization via truncation

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be truncated.

        Returns
        -------
        Torus
            Torus instance with larger discretization.
        """
        if dimension == 'time':
            truncate_number = int(size // 2) - 1
            # Split into real and imaginary components, truncate separately.
            first_half = self.state[:truncate_number+1, :]
            second_half = self.state[-self.n:-self.n+truncate_number, :]
            truncated_modes = np.concatenate((first_half, second_half), axis=0)
        else:
            truncate_number = int(size // 2) - 1
            # Split into real and imaginary components, truncate separately.
            first_half = self.state[:, :truncate_number]
            second_half = self.state[:, -self.m:-self.m + truncate_number]
            truncated_modes = np.concatenate((first_half, second_half), axis=1)
        return self.__class__(state=truncated_modes, statetype=self.statetype, T=self.T, L=self.L, S=self.S)

    def parameter_dependent_filename(self, extension='.h5', decimals=3):

        Lsplit = str(self.L).split('.')
        Lint = str(Lsplit[0])
        Ldec = str(Lsplit[1])
        Lname = ''.join([Lint, 'p', Ldec[:decimals]])

        Tsplit = str(self.T).split('.')
        Tint = str(int(Tsplit[0]))
        Tdec = str(int(Tsplit[1]))
        Tname = ''.join([Tint, 'p', Tdec[:decimals]])

        save_filename = ''.join([self.__class__.__name__, '_L', Lname, '_T', Tname, extension])
        return save_filename

    def plot(self, show=True, save=False, padding=True, fundamental_domain=True, **kwargs):
        """ Plot the velocity field as a 2-d density plot using matplotlib's imshow

        Parameters
        ----------
        show : bool
            Whether or not to display the figure
        save : bool
            Whether to save the figure
        padding : bool
            Whether to interpolate with zero padding before plotting. (Increases the effective resolution).
        fundamental_domain : bool
            Whether to plot only the fundamental domain or not.
        **kwargs :
            newN : int
                Even integer for the new discretization size in time
            newM : int
                Even integer for the new discretization size in space.
            filename : str
                The save name of the figure, if save==True
            directory : str
                The location to save to, if save==True
        Notes
        -----
        newN and newM are accessed via .get() because this is the only manner in which to incorporate
        the current N and M values as defaults.

        """
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.rcParams.update({'font.size': 16})
        verbose = kwargs.get('verbose', False)

        if padding:
            pad_n, pad_m = kwargs.get('newN', 16*self.N), kwargs.get('newM', 16*self.M)
            plot_torus_tmp = rediscretize(self, newN=pad_n, newM=pad_m)
        else:
            plot_torus_tmp = self

        # The following creates custom tick labels and accounts for some pathological cases
        # where the period is too small (only a single label) or too large (many labels, overlapping due
        # to font size) Default label tick size is 10 for time and the fundamental frequency, 2 pi sqrt(2) for space.
        if fundamental_domain:
            torus_to_plot = plot_torus_tmp.to_fundamental_domain().convert(to='field')
        else:
            torus_to_plot = plot_torus_tmp.convert(to='field')

        if torus_to_plot.T != 0:
            timetick_step = np.min([10, 10 * (2**(int(np.log10(torus_to_plot.T))))])
            yticks = np.arange(timetick_step, torus_to_plot.T, timetick_step)
            ylabels = np.array([str(int(y)) for y in yticks])
        else:
            torus_to_plot.T = 1
            yticks = np.array([0, torus_to_plot.T])
            ylabels = np.array(['0', 'inf'])

        if torus_to_plot.L > 2*pi:
            xticks = np.arange(0, torus_to_plot.L, 2*pi)
            xlabels = [str(int(x/(2*pi))) for x in xticks]
        elif torus_to_plot.L > pi:
            xticks = np.arange(0, torus_to_plot.L, pi)
            xlabels = [str(int(x/pi)) for x in xticks]
        else:
            torus_to_plot.L = 1
            xticks = np.array([0, torus_to_plot.L])
            xlabels = np.array(['0', 'inf'])

        # Modify the size so that relative sizes between different figures is approximately representative
        # of the different sizes; helps with side-by-side comparison.
        _figsize = (max([2, 2**np.log10(torus_to_plot.L)]), max([2, 2**np.log10(torus_to_plot.T)]))

        fig, ax = plt.subplots(figsize=_figsize)
        # plot the field
        image = ax.imshow(torus_to_plot.state, extent=[0, torus_to_plot.L, 0, torus_to_plot.T], cmap='jet')
        # Include custom ticks and tick labels
        ax.set_xticks(xticks)
        ax.set_yticks(yticks)
        ax.set_xticklabels(xlabels, fontsize=12)
        ax.set_yticklabels(ylabels, fontsize=12)
        ax.grid(True, linestyle=':', color='k', alpha=0.8)
        fig.subplots_adjust(right=0.9)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size=0.1, pad=0.02)

        # Custom colorbar values
        maxu = np.max(torus_to_plot.state.ravel())
        minu = np.min(torus_to_plot.state.ravel())
        plt.colorbar(image, cax=cax, ticks=[round(minu, 1) + 0.1, round(maxu, 1)-0.1])
        plt.tight_layout()

        if save:
            filename = kwargs.get('filename', None)
            directory = kwargs.get('directory', '')

            # Create save name if one doesn't exist.
            if filename is None:
                filename = self.parameter_dependent_filename(extension='.png')
            elif filename.endswith('.h5'):
                filename = filename.split('.h5')[0] + '.png'

            # Create save directory if one doesn't exist.
            if directory is None:
                pass
            else:
                if directory == 'default':
                    directory = os.path.join(os.path.abspath(os.path.join(os.getcwd(), '../figs/')), '')
                elif directory == '':
                    pass
                elif not os.path.isdir(directory):
                    warnings.warn('Trying to save figure to a directory that does not exist:' + directory, Warning)
                    sys.stdout.flush()
                    proceed = input('Would you like to create this directory? [y]/[n]')
                    if proceed == 'y':
                        os.mkdir(directory)
                    else:
                        directory = ''

                filename = os.path.join(directory, filename)
            if verbose:
                print('Saving figure to {}'.format(filename))
            plt.savefig(filename, bbox_inches='tight', pad_inches=0)

        if show:
            plt.show()
        else:
            plt.close()

        return None

    def precondition(self, target, fixedparams=(False, False)):
        """ Precondition a vector with the inverse (aboslute value) of linear spatial terms

        Parameters
        ----------

        target : Torus
            Torus to precondition
        fixedparams : (bool, bool)
            Whether or not period T or spatial period L are fixed.

        Returns
        -------
        target : Torus
            Return the Torus instance, modified by preconditioning.
        """
        qk_matrix = self.elementwise_dx()
        p_matrix = np.abs(self.elementwise_dt()) + qk_matrix**2 + qk_matrix**4
        target.state = np.divide(target.state, p_matrix)

        # Precondition the change in T and L so that they do not dominate
        if not fixedparams[0]:
            target.T = target.T / self.T
        if not fixedparams[1]:
            target.L = target.L / (self.L**4)

        return target

    def preconditioner(self, fixedparams=(False, False), side='left'):
        """ Preconditioning matrix

        Parameters
        ----------
        fixedparams : (bool, bool)
            Whether or not period T or spatial period L are fixed.
        side : str
            Takes values 'left' or 'right'. This is an accomodation for
            the typically rectangular Jacobian matrix.

        Returns
        -------
        matrix :
            Preconditioning matrix

        """
        # Preconditioner is the inverse of the aboslute value of the linear spatial derivative operators.
        qk_matrix = self.elementwise_dx()
        ptmp = 1 / (np.abs(self.elementwise_dt()) + qk_matrix**2 + qk_matrix**4)
        p = ptmp.ravel()
        parameters = []
        # If including parameters, need an extra diagonal matrix to account for this (right-side preconditioning)
        if side == 'right':
            if not fixedparams[0]:
                parameters.append(1 / self.T)
            if not fixedparams[1]:
                parameters.append(1 / (self.L**4))
            parameters = np.array(parameters).reshape(1, -1)
            p_row = np.concatenate((p.reshape(1, -1), parameters.reshape(1, -1)), axis=1)
            return np.tile(p_row, (p.size, 1))
        else:
            return np.tile(p.reshape(-1, 1), (1, p.size+(2-sum(fixedparams))))

    def pseudospectral(self, other, qk_matrix):
        """ Pseudospectral computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        Parameters
        ----------

        other : Torus
            The second component of the pseudospectral product see Notes for details
        qk_matrix : matrix
            The matrix with the correctly ordered spatial frequencies.

        Notes
        -----
        The pseudospectral product is the name given to the elementwise product equivalent to the
        convolution of spatiotemporal Fourier modes. It's faster and more accurate hence why it is used.
        The matrix vector product takes the form d_x (u * v), but the "normal" usage is d_x (u * u); in the latter
        case other is the same as self. The spatial frequency matrix is passed to avoid redundant function calls,
        improving speed.

        """
        # Elementwise product
        pseudospectral_torus = self.convert(to='field').statemul(other.convert(to='field')).convert(to='modes')
        # Spatial derivative with 1/2 factor
        pseudospectral_torus.state = 0.5 * swap_modes(np.multiply(qk_matrix, pseudospectral_torus.state))
        return pseudospectral_torus

    def rpseudospectral(self, other, qk_matrix):
        """ Pseudospectral computation of the nonlinear term of the adjoint Kuramoto-Sivashinsky equation

        Parameters
        ----------

        other : Torus
            The second component of the pseudospectral product see Notes for details
        qk_matrix : matrix
            The matrix with the correctly ordered spatial frequencies.

        Notes
        -----
        The pseudospectral product is the name given to the elementwise product equivalent to the
        convolution of spatiotemporal Fourier modes. It's faster and more accurate hence why it is used.
        The matrix vector product takes the form -1 * u * d_x v. The spatial frequency matrix is passed to avoid
        redundant function calls, improving speed.

        """
        # Take spatial derivative
        other.state = swap_modes(np.multiply(qk_matrix, other.convert(to='modes').state))
        # Elementwise product
        return -1.0 * self.convert(to='field').statemul(other.convert(to='field')).convert(to='modes')

    def random_initial_condition(self, T, L, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes

        Parameters
        ----------
        T : float
            Time period
        L : float
            Space period

        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            Torus whose state has been modified to be a set of random Fourier modes.

        Notes
        -----
        Anecdotal evidence suggests that "worse" initial conditions converge more often to solutions of the
        predetermined symmetry group. In other words it's better to start far away from the chaotic attractor
        because then it is less likely to start near equilibria. Spatial scale currently unused, still testing
        for the best random fields.

        """
        if T == 0.:
            self.T = 20 + 100*np.random.rand(1)
        else:
            self.T = T
        if L == 0.:
            self.L = 22 + 44*np.random.rand(1)
        else:
            self.L = L

        spectrum_type = kwargs.get('spectrum', 'random')
        self.N = kwargs.get('N', np.max([32, 2**(int(np.log2(self.T)-1))]))
        self.M = kwargs.get('M', np.max([2**(int(np.log2(self.L))), 32]))
        self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1

        if spectrum_type == 'random':
            time_scale = np.min([kwargs.get('time_scale', self.n), self.n])
            space_scale = np.min([kwargs.get('space_scale', self.m), self.m])
            # Account for different sized spectra
            rmodes = np.random.randn(self.N-1, self.M-2)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0 ** mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier[time_scale:, :] = 0
            mollifier = np.concatenate((mollifier, mollifier), axis=1)
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, self.M-2]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)
        elif spectrum_type == 'gaussian':
            time_scale = np.min([kwargs.get('time_scale', self.n), self.n])
            space_scale = np.min([kwargs.get('space_scale', self.m), self.m])
            # Account for different sized spectra
            rmodes = np.random.randn(self.N-1, self.M-2)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0 ** mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier[time_scale:, :] = 0
            mollifier = np.concatenate((mollifier, mollifier), axis=1)
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, self.M-2]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)

        self.convert(to='field', inplace=True)
        self.state = (self // (1.0/4.0)).state
        self.convert(to='modes', inplace=True)
        return self

    def reflection(self):
        """ Reflect the velocity field about the spatial midpoint

        Returns
        -------
        Torus :
            Torus whose state is the reflected velocity field -u(-x,t).
        """
        # Different points in space represented by columns of the state array
        reflected_field = -1.0*np.roll(np.fliplr(self.convert(to='field').state), 1, axis=1)
        return self.__class__(state=reflected_field, statetype='field', T=self.T, L=self.L, S=self.S)

    def residual(self):
        """ The value of the cost function

        Returns
        -------
        float :
            The value of the cost function, equal to 1/2 the squared L_2 norm of the spatiotemporal mapping,
            R = 1/2 ||F||^2.
        """
        return 0.5 * np.linalg.norm(self.convert(to='modes').spatiotemporal_mapping().state.ravel())**2

    def rmatvec(self, other, fixedparams=(False, False), preconditioning=True):
        """ Matrix-vector product with the adjoint of the Jacobian

        Parameters
        ----------
        other : Torus
            Torus whose state represents the vector in the matrix-vector product.
        fixedparams : (bool, bool)
            Whether or not period T or spatial period L are fixed.
        preconditioning : bool
            Whether or not to apply (left) preconditioning to the adjoint matrix vector product.

        Returns
        -------
        rmatvec_torus :
            Torus with values representative of the adjoint-vector product A^H * x.

        """

        # Linear component of the product, equal to -v_t + v_xx + v_xxxx
        wj_matrix = self.elementwise_dt()
        qk_matrix = self.elementwise_dx()
        elementwise_qk2 = -1.0*qk_matrix**2
        elementwise_qk4 = qk_matrix**4

        dt = swap_modes(np.multiply(wj_matrix, other.state), dimension='time')
        d2x = np.multiply(elementwise_qk2, other.state)
        d4x = np.multiply(elementwise_qk4, other.state)
        linear_component = -1.0*dt + d2x + d4x
        linear_torus = self.__class__(state=linear_component, T=self.T, L=self.L, S=self.S)

        # Nonlinear component, equal to -u * v_x
        field_torus = self.convert(to='field')
        rmatvec_torus = linear_torus + field_torus.rpseudospectral(other, qk_matrix)

        if not fixedparams[0]:
            # Derivative with respect to T term equal to DF/DT * v
            dt_self = swap_modes(np.multiply(wj_matrix, self.state), dimension='time')
            dfdt = (-1.0 / self.T)*dt_self
            rmatvec_torus.T = np.dot(dfdt.ravel(), other.state.ravel())

        if not fixedparams[1]:
            # Derivative with respect to L equal to DF/DL * v
            d2x_self = np.multiply(elementwise_qk2, self.state)
            d4x_self = np.multiply(elementwise_qk4, self.state)
            dfdl_linear = ((-2.0/self.L)*d2x_self + (-4.0/self.L)*d4x_self)
            dfdl_nonlinear = (-1.0/self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear
            rmatvec_torus.L = np.dot(dfdl.ravel(), other.state.ravel())

        if preconditioning:
            # Apply left preconditioning
            p_matrix = 1.0 / (np.abs(wj_matrix) + qk_matrix**2 + qk_matrix**4)
            rmatvec_torus.state = np.multiply(rmatvec_torus.state, p_matrix)

            if not fixedparams[0]:
                rmatvec_torus.T = rmatvec_torus.T / self.T
            if not fixedparams[1]:
                rmatvec_torus.L = rmatvec_torus.L/(self.L**4)

        return rmatvec_torus

    def rotate(self, distance=0, direction='space', inplace=False):
        """ Rotate the velocity field in either space or time.

        Parameters
        ----------
        distance : float
            The rotation / translation amount, in dimensionless units of time or space.
        direction : str
            Takes values 'space' or 'time'. Direction which rotation will be performed in.
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose field has been rotated.

        Notes
        -----
        Due to periodic boundary conditions, translation is equivalent to rotation on a fundemantal level here.
        Hence the use of 'distance' instead of 'angle'. This can be negative. Also due to the periodic boundary
        conditions, a distance equaling the entire domain length is equivalent to no rotation. I.e.
        the rotation is always modulo L or modulo T.

        """
        if direction == 'space':
            thetak = distance*self.wave_vector()
        else:
            thetak = distance*self.frequency_vector()

        cosinek = np.cos(thetak)
        sinek = np.sin(thetak)
        original_statetype = copy.copy(self.statetype)

        if direction == 'space':
            self.convert(to='s_modes')
            # Rotation breaks discrete symmetry and destroys the solution.
            if self.__class__.__name__ in ['ShiftReflectionTorus', 'AntisymmetricTorus']:
                warnings.warn('Performing a spatial rotation on a torus with discrete symmetry is greatly discouraged.')

            # Refer to rotation matrix in 2-D for reference.
            cosine_block = np.tile(cosinek.reshape(1, -1), (self.N, 1))
            sine_block = np.tile(sinek.reshape(1, -1), (self.N, 1))

            # Rotation performed on spatial modes because otherwise rotation is ill-defined for Antisymmetric and
            # Shift-reflection symmetric tori.
            spatial_modes_real = self.state[:, :-self.m]
            spatial_modes_imaginary = self.state[:, -self.m:]
            rotated_real = (np.multiply(cosine_block, spatial_modes_real)
                            + np.multiply(sine_block, spatial_modes_imaginary))
            rotated_imag = (-np.multiply(sine_block, spatial_modes_real)
                            + np.multiply(cosine_block, spatial_modes_imaginary))
            rotated_s_modes = np.concatenate((rotated_real, rotated_imag), axis=1)
            if inplace:
                self.state = rotated_s_modes
                self.statetype = 's_modes'
                self.convert(to=original_statetype)
                return self
            else:
                return self.__class__(state=rotated_s_modes, statetype='s_modes',
                                      T=self.T, L=self.L, S=self.S).convert(to=original_statetype)
        else:
            self.convert()
            # Refer to rotation matrix in 2-D for reference.
            cosine_block = np.tile(cosinek.reshape(-1, 1), (1, self.state.shape[1]))
            sine_block = np.tile(sinek.reshape(-1, 1), (1, self.state.shape[1]))

            modes_timereal = self.state[1:-self.n, :]
            modes_timeimaginary = self.state[-self.n:, :]
            # Elementwise product to account for matrix product with "2-D" rotation matrix
            rotated_real = np.multiply(cosine_block, modes_timereal) - np.multiply(sine_block, modes_timeimaginary)
            rotated_imag = np.multiply(sine_block, modes_timereal) + np.multiply(cosine_block, modes_timeimaginary)
            time_rotated_modes = np.concatenate((self.state[0, :].reshape(1, -1), rotated_real, rotated_imag), axis=0)
            if inplace:
                self.state = time_rotated_modes
                self.statetype = 'modes'
                self.convert(to=original_statetype)
                return self
            else:
                self.convert(to=original_statetype)
                return self.__class__(state=time_rotated_modes,
                                      T=self.T, L=self.L, S=self.S).convert(to=original_statetype)

    def shift_reflection(self):
        """ Return a Torus with shift-reflected velocity field

        Returns
        -------
        Torus :
            Torus with shift-reflected velocity field

        Notes
        -----
            Shift reflection in this case is a composition of spatial reflection and temporal translation by
            half of the period. Because these are in different dimensions these operations commute.
        """
        shift_reflected_field = np.roll(-1.0*np.roll(np.fliplr(self.state), 1, axis=1), self.n, axis=0)
        return self.__class__(state=shift_reflected_field, statetype='field', T=self.T, L=self.L, S=self.S)

    def space_fft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        space_modes = rfft(self.state, norm='ortho', axis=1)[:, 1:-1]
        spatial_modes = np.concatenate((space_modes.real, space_modes.imag), axis=1)
        if inplace:
            self.statetype = 's_modes'
            self.state = spatial_modes
            return self
        else:
            return self.__class__(state=spatial_modes, statetype='s_modes', T=self.T, L=self.L, S=self.S)

    def space_ifft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Make the modes complex valued again.
        complex_modes = self.state[:, :-self.m] + 1j * self.state[:, -self.m:]
        # Re-add the zeroth and Nyquist spatial frequency modes (zeros) and then transform back
        z = np.zeros([self.N, 1])
        field = irfft(np.concatenate((z, complex_modes, z), axis=1), norm='ortho', axis=1)
        if inplace:
            self.statetype = 'field'
            self.state = field
            return self
        else:
            return self.__class__(state=field, statetype='field', T=self.T, L=self.L, S=self.S)

    def space_ifft_matrix(self):
        """ Inverse spatial Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial Fourier modes into a physical field u(x,t).

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the inverse Fourier transform.
        """

        idft_mat_real = irfft(np.eye(self.M//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        idft_mat_imag = irfft(1j*np.eye(self.M//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        space_idft_mat = np.concatenate((idft_mat_real, idft_mat_imag), axis=1)
        return np.kron(np.eye(self.N), space_idft_mat)

    def space_fft_matrix(self):
        """ Spatial Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a physical field u(x,t) into a set of spatial Fourier modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        
        dft_mat = rfft(np.eye(self.M), norm='ortho', axis=0)[1:-1, :]
        space_dft_mat = np.concatenate((dft_mat.real, dft_mat.imag), axis=0)
        return np.kron(np.eye(self.N), space_dft_mat)

    def spacetime_ifft(self, inplace=False):
        """ Inverse space-time Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus instance in the physical field basis.
        """
        if inplace:
            self.time_ifft(inplace=True).space_ifft(inplace=True)
            self.statetype = 'field'
            return self
        else:
            return self.time_ifft().space_ifft()

    def spacetime_fft(self, inplace=False):
        """ Space-time Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus instance in the spatiotemporal mode basis.
        """
        if inplace:
            self.space_fft(inplace=True).time_fft(inplace=True)
            self.statetype = 'modes'
            return self
        else:
            # Return transform of field
            return self.space_fft().time_fft()

    def spacetime_ifft_matrix(self):
        """ Inverse Space-time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a physical field u(x,t)

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        return np.dot(self.space_ifft_matrix(), self.time_ifft_matrix())

    def spacetime_fft_matrix(self):
        """ Space-time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a physical field u(x,t) into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        return np.dot(self.time_fft_matrix(), self.space_fft_matrix())

    def spatiotemporal_mapping(self):
        """ The Kuramoto-Sivashinsky equation evaluated at the current state.

        Returns
        -------
        Torus :
            Torus whose state is representative of the equation u_t + u_xx + u_xxxx + 1/2 (u^2)_x
        :return:
        """
        # For specific computation of the linear component instead
        # of arbitrary derivatives we can optimize the calculation by being specific.

        wj_matrix = self.elementwise_dt()
        qk_matrix = self.elementwise_dx()
        elementwise_d2xd4x = -1.0*qk_matrix**2 + qk_matrix**4
        linear_component = (np.multiply(elementwise_d2xd4x, self.state)
                            + swap_modes(np.multiply(wj_matrix, self.state), dimension='time'))
        linear_torus = self.__class__(state=linear_component)

        # Convert state information to field inplace; derivative operation switches this back to modes?
        field_torus = self.convert(to='field')
        mapping_torus = linear_torus + field_torus.pseudospectral(field_torus, qk_matrix)

        return mapping_torus

    def statemul(self, other):
        """ Elementwise multiplication of two Tori states

        Returns
        -------
        Torus :
            The Torus representing the product.

        Notes
        -----
        Only really makes sense when taking an elementwise product between Tori defined on spatiotemporal
        domains of the same size.
        """
        return self.__class__(state=np.multiply(self.state, other.state),
                              statetype=self.statetype, T=self.T, L=self.L, S=self.S)

    def time_fft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, :]
        modes_imag = modes.imag[1:-1, :]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)

        if inplace:
            self.statetype = 'modes'
            self.state = spacetime_modes
            return self
        else:
            return self.__class__(state=spacetime_modes, statetype='modes', T=self.T, L=self.L, S=self.S)

    def time_ifft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        time_real = modes[:-self.n, :]
        time_imaginary = np.concatenate((np.zeros([1, self.mode_shape[1]]), modes[-self.n:, :]), axis=0)
        complex_modes = np.concatenate((time_real + 1j * time_imaginary, np.zeros([1, self.mode_shape[1]])), axis=0)
        space_modes = irfft(complex_modes, norm='ortho', axis=0)

        if inplace:
            self.statetype = 's_modes'
            self.state = space_modes
            return self
        else:
            return self.__class__(state=space_modes, statetype='s_modes', T=self.T, L=self.L, S=self.S)

    def time_fft_matrix(self):
        """ Inverse Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a set of spatial modes

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        dft_mat = rfft(np.eye(self.N), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((dft_mat[:-1, :].real,
                                        dft_mat[1:-1, :].imag), axis=0)
        return np.kron(time_idft_mat, np.eye(self.M-2))

    def time_ifft_matrix(self):
        """ Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial modes into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        idft_mat_real = irfft(np.eye(self.N//2 + 1), norm='ortho', axis=0)
        idft_mat_imag = irfft(1j * np.eye(self.N//2 + 1), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((idft_mat_real[:, :-1],
                                        idft_mat_imag[:, 1:-1]), axis=1)
        return np.kron(time_idft_mat, np.eye(self.M-2))

    def to_fundamental_domain(self, **kwargs):
        """ Placeholder for subclassees, included for compatibility"""
        return self

    def to_h5(self, filename=None, directory='', verbose=False):
        """ Export current state information to HDF5 file

        Parameters
        ----------
        filename : str
            Name for the save file
        directory :
            Location to save at
        verbose : If true, prints save messages to std out
        """
        if filename is None:
            filename = self.parameter_dependent_filename()
        elif filename == 'initial':
            filename = 'initial_' + self.parameter_dependent_filename()

        if directory == 'default':
            directory = os.path.join(os.path.abspath(os.path.join(os.getcwd(), '../data/')), '')
        elif directory == '':
            pass
        elif not os.path.isdir(directory):
            warnings.warn('Trying to save figure to a directory that does not exist:' + directory, Warning)
            sys.stdout.flush()
            proceed = input('Would you like to create this directory? If no, '
                            'then figure will save where current script is located [y]/[n]')
            if proceed == 'y':
                os.mkdir(directory)

        filename = os.path.join(directory, filename)
        if verbose:
            print('Saving data to {}'.format(filename))
        with h5py.File(filename, 'w') as f:
            f.create_dataset("field", data=self.convert(to='field').state)
            f.create_dataset("speriod", data=self.L)
            f.create_dataset("period", data=self.T)
            f.create_dataset("space_discretization", data=self.M)
            f.create_dataset("time_discretization", data=self.N)
            f.create_dataset("spatial_shift", data=self.S)
            f.create_dataset("residual", data=float(self.residual()))
        return None

    def wave_vector(self):
        """ Spatial frequency vector for the current state

        Returns
        -------
        ndarray :
            Array of spatial frequencies of shape (m, 1)
        """
        return ((2 * pi * self.M / self.L) * np.fft.fftfreq(self.M)[1:self.m+1]).reshape(1, -1)


class RelativeTorus(Torus):

    def __init__(self, state=None, statetype='modes', T=0., L=0., S=0., **kwargs):
        super().__init__(state=state, statetype=statetype, T=T, L=L, **kwargs)

        self.comoving_frame = 'comoving'

    def calculate_shift(self):
        """ Calculate the phase difference between the spatial modes at t=0 and t=T """
        s_modes = self.convert(inplace=False, to='s_modes')
        modes1 = s_modes[-1, :].reshape(-1, 1)
        modes0 = s_modes[0, :].reshape(-1, 1)
        angle = np.arccos(np.dot(np.transpose(modes1), modes0)/(np.linalg.norm(modes1)*np.linalg.norm(modes0)))
        shift = (self.L / (2 * pi)) * angle
        return shift

    def comoving_mapping_component(self):
        """ Co-moving frame component of spatiotemporal mapping """
        return -1.0 * (self.S / self.T)*self.dx()

    def comoving_matrix(self):
        """ Operator that constitutes the co-moving frame term """
        return -1.0 * (self.S / self.T)*self.dx_matrix()

    def comoving_transformation(self, inplace=False):
        """ Transform to (or from) the co-moving frame depending on the current reference frame

        Parameters
        ----------
        inplace : bool
            Whether to perform in-place or not

        Returns
        -------
        RelativeTorus :
            RelativeTorus in transformed reference frame.
        """
        original_state = self.statetype
        s_modes = self.convert(inplace=False, to='s_modes').state
        time_vector = np.flipud(np.linspace(0, self.T, num=self.N, endpoint=True)).reshape(-1, 1)
        translation_per_period = -1.0 * self.S / self.T
        time_dependent_translations = translation_per_period*time_vector
        thetak = time_dependent_translations.reshape(-1, 1)*self.wave_vector().ravel()
        cosine_block = np.cos(thetak)
        sine_block = np.sin(thetak)
        real_modes = s_modes[:, :-self.m]
        imag_modes = s_modes[:, -self.m:]
        frame_rotated_s_modes_real = (np.multiply(real_modes, cosine_block) 
                                      - np.multiply(imag_modes, sine_block))
        frame_rotated_s_modes_imag = (np.multiply(real_modes, sine_block) 
                                      + np.multiply(imag_modes, cosine_block))
        frame_rotated_s_modes = np.concatenate((frame_rotated_s_modes_real, frame_rotated_s_modes_imag), axis=1)

        if inplace:
            self.state = frame_rotated_s_modes
            self.statetype = 's_modes'
            self.S = -1.0 * self.S
            self.convert(to=original_state)
            return self
        else:
            return self.__class__(state=frame_rotated_s_modes, statetype='s_modes',
                                  T=self.T, L=self.L, S=-1.0*self.S).convert(to=original_state)

    def from_fundamental_domain(self, inplace=False):
        return self.comoving_transformation(inplace=inplace)

    def increment(self, other, stepsize=1):
        """ Add optimization correction to current state

        Parameters
        ----------
        other : RelativeTorus
            Represents the values to increment by.
        stepsize : float
            Multiplicative factor which decides the step length of the correction.

        Returns
        -------
        RelativeTorus :
            New Torus which results from adding an optimization correction to self.
        """
        return self.__class__(state=self.state+stepsize*other.state,
                              T=self.T+stepsize*other.T, L=self.L+stepsize*other.L, S=self.S+stepsize*other.S)

    def jac(self, fixedparams=(False, False, False)):
        """ Jacobian that includes the spatial translation term for relative periodic tori

        Parameters
        ----------
        fixedparams : (bool, bool, bool)
            Determines whether or not the various parameters, period, spatial period, spatial shift, (T,L,S)
            are variables or not.

        Returns
        -------
        matrix :
            Jacobian matrix for relative periodic tori.
        """
        # The linearization matrix of the governing equations.
        jac_ = self.jac_lin() + self.jac_nonlin()

        # If period is not fixed, need to include dF/dT for changes to period.
        if not fixedparams[0]:
            dt = swap_modes(np.multiply(self.elementwise_dt(), self.state), dimension='time')
            dfdt = (-1.0 / self.T)*dt.reshape(1, -1)
            jac_ = np.concatenate((jac_, dfdt.reshape(-1, 1)), axis=1)

        # If period is not fixed, need to include dF/dL for changes to period.
        if not fixedparams[1]:
            field_torus = self.convert(to='field')
            qk_matrix = self.elementwise_dx()
            d2x = np.multiply(-1.0*qk_matrix**2, self.state)
            d4x = np.multiply(qk_matrix**4, self.state)
            dfdl_linear = (-2.0/self.L)*d2x+(-4.0/self.L)*d4x
            dfdl_nonlinear = - 1.0/self.L * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear
            jac_ = np.concatenate((jac_, dfdl.reshape(-1, 1)), axis=1)

        if not fixedparams[2]:
            dfds = swap_modes(np.multiply(self.elementwise_dx(), self.state), dimension='space')
            jac_ = np.concatenate((jac_, (-1.0 / self.T) * dfds.reshape(-1, 1)), axis=1)

        return jac_

    def jac_lin(self):
        """ Extension of the Torus method that includes the term for spatial translation symmetry"""
        return super().jac_lin() + self.comoving_matrix()

    def spatiotemporal_mapping(self):
        """ Extension of Torus method to include co-moving frame term. """
        return super().spatiotemporal_mapping() + self.comoving_mapping_component()

    def matvec(self, other, fixedparams=(False, False, False), preconditioning=True, **kwargs):
        """ Extension of parent class method

        Parameters
        ----------
        other : RelativeTorus
            Torus instance whose state represents the vector in the matrix-vector multiplication.
        fixedparams : tuple of bool
            Determines whether to include period and spatial period
            as variables.
        preconditioning : bool
            Whether or not to apply (left) preconditioning P (Ax)

        Returns
        -------
        RelativeTorus
            RelativeTorus whose state and other parameters result from the matrix-vector product.

        Notes
        -----
        Equivalent to computation of (v_t + v_xx + v_xxxx + phi * v_x) + d_x (u .* v)
        The reason for all of the repeated code is that the co-moving terms re-use the same matrices
        as the other terms; this prevents additional function calls.
        """
        wj_matrix = self.elementwise_dt()
        qk_matrix = self.elementwise_dx()
        elementwise_qk2 = -1.0*qk_matrix**2
        elementwise_qk4 = qk_matrix**4

        dt = swap_modes(np.multiply(wj_matrix, other.state), dimension='time')
        d2x = np.multiply(elementwise_qk2, other.state)
        d4x = np.multiply(elementwise_qk4, other.state)
        s = -1.0 * (self.S / self.T)*swap_modes(np.multiply(qk_matrix, other.state))

        linear_term = dt + d2x + d4x + s
        linear_torus = self.__class__(state=linear_term, statetype='modes', T=self.T, L=self.L, S=self.S)

        field_torus = self.convert(to='field')
        # Convert state information to field inplace; derivative operation switches this back to modes?
        matvec_torus = linear_torus + 2 * field_torus.pseudospectral(other, qk_matrix)

        if not fixedparams[0]:
            dt_self = swap_modes(np.multiply(wj_matrix, self.state), dimension='time')
            s_self = (-1.0 * self.S / self.T)*swap_modes(np.multiply(qk_matrix, self.state))
            dfdt = (-1.0 / self.T)*(dt_self+s_self)
            matvec_torus.state = matvec_torus.state + other.T*dfdt

        if not fixedparams[1]:
            d2x_self = np.multiply(elementwise_qk2, self.state)
            d4x_self = np.multiply(elementwise_qk4, self.state)
            s_self = (-1.0 * self.S / self.T)*swap_modes(np.multiply(qk_matrix, self.state))
            dfdl_linear = (-2.0/self.L)*d2x_self + (-4.0/self.L)*d4x_self + (-1.0/self.L)*s_self
            dfdl_nonlinear = (-1.0/self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear
            # Derivative of mapping with respect to T is the same as -1/T * u_t
            matvec_torus.state = matvec_torus.state + other.L*dfdl

        if not fixedparams[2]:
            matvec_torus.state = (matvec_torus.state
                                  + other.S*(-1.0 / self.T)*swap_modes(np.multiply(qk_matrix, self.state)))

        if preconditioning:
            p_matrix = 1.0 / (np.abs(wj_matrix) + qk_matrix**2 + qk_matrix**4)
            matvec_torus.state = np.multiply(matvec_torus.state, p_matrix)

        return matvec_torus

    def rmatvec(self, other, fixedparams=(False, False, False), preconditioning=True, **kwargs):
        """ Extension of the parent method to RelativeTorus """
        # For specific computation of the linear component instead
        # of arbitrary derivatives we can optimize the calculation by being specific.
        wj_matrix = self.elementwise_dt()
        qk_matrix = self.elementwise_dx()
        elementwise_qk2 = -1.0*qk_matrix**2
        elementwise_qk4 = qk_matrix**4

        dt = -1.0 * swap_modes(np.multiply(wj_matrix, other.state), dimension='time')
        d2x = np.multiply(elementwise_qk2, other.state)
        d4x = np.multiply(elementwise_qk4, other.state)
        s = (self.S / self.T)*swap_modes(np.multiply(qk_matrix, other.state))
        linear_component = dt + d2x + d4x + s
        linear_torus = self.__class__(state=linear_component)
        field_torus = self.convert(to='field')
        rmatvec_torus = linear_torus + field_torus.rpseudospectral(other, qk_matrix)

        if not fixedparams[0]:
            dt_self = swap_modes(np.multiply(wj_matrix, self.state), dimension='time')
            s_self = (-1.0 * self.S / self.T)*swap_modes(np.multiply(qk_matrix, self.state))
            dfdt = (-1.0 / self.T)*(dt_self+s_self)
            rmatvec_torus.T = np.dot(dfdt.ravel(), other.state.ravel())

        if not fixedparams[1]:
            d2x_self = np.multiply(elementwise_qk2, self.state)
            d4x_self = np.multiply(elementwise_qk4, self.state)
            s_self = (-1.0 * self.S / self.T)*swap_modes(np.multiply(qk_matrix, self.state))
            dfdl_linear = (-2.0/self.L)*d2x_self + (-4.0/self.L)*d4x_self + (-1.0/self.L)*s_self
            dfdl_nonlinear = (-1.0/self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear

            # Derivative of mapping with respect to T is the same as -1/T * u_t
            rmatvec_torus.L = np.dot(dfdl.ravel(), other.state.ravel())

        if not fixedparams[2]:
            rmatvec_torus.S = ((-1.0 / self.T)
                               * np.dot(swap_modes(np.multiply(qk_matrix, self.state)).ravel(), other.state.ravel()))

        if preconditioning:
            p_matrix = 1.0 / (np.abs(wj_matrix) + qk_matrix**2 + qk_matrix**4)
            rmatvec_torus.state = np.multiply(rmatvec_torus.state, p_matrix)

            if not fixedparams[0]:
                rmatvec_torus.T = rmatvec_torus.T / self.T

            if not fixedparams[1]:
                rmatvec_torus.L = rmatvec_torus.L / (self.L**4)

        return rmatvec_torus

    def random_initial_condition(self):
        """ Extension of parent modes to include spatial-shift initialization """
        super().random_initial_condition()
        self.S = self.L * np.random.rand(1)
        if S == 0.0:
            # Assign random proportion of L with random sign as the shift if none provided.
            self.S = ([-1, 1][int(2*np.random.rand())])*np.random.rand()*self.L
        else:
            self.S = S
        return self

    def state_vector(self):
        """ Vector which completely describes the torus."""
        return np.concatenate((self.state.reshape(-1, 1),
                               [[float(self.T)]], [[float(self.L)]], [[float(self.S)]]), axis=0)

    def to_fundamental_domain(self, inplace=False):
        """ Transform reference frame """
        return self.comoving_transformation(inplace=inplace)


class ShiftReflectionTorus(Torus):

    def __init__(self, state=None, statetype='modes', T=0., L=0., **kwargs):
        try:
            if state is not None:
                shp = state.shape
                self.state = state
                self.statetype = statetype
                if statetype == 'modes':
                    self.N, self.M = shp[0] + 1, 2*shp[1] + 2
                elif statetype == 'field':
                    self.N, self.M = shp
                elif statetype == 's_modes':
                    self.N, self.M = shp[0], shp[1]+2
                self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
                self.T, self.L = T, L
            else:
                self.random_initial_condition(T=T, L=L, **kwargs)

            self.mode_shape = (self.N-1, self.m)
            # For uniform save format
            self.S = 0.
        except ValueError:
            print('Incompatible type provided for field or modes: 2-D NumPy arrays only')

    def __copy__(self):
        return self.__class__(state=self.state, T=self.T, L=self.L, S=self.S)

    def dx(self, order=1):
        """ Overwrite of parent method """
        qkn = self.wave_vector()**order
        if np.mod(order, 2):
            c1, c2 = so2_coefficients(order=order)
            elementwise_dxn = np.tile(np.concatenate((c1*qkn, c2*qkn), axis=1), (self.N, 1))
            dxn_s_modes = np.multiply(elementwise_dxn, self.convert(inplace=False, to='s_modes').state)
            dxn_s_modes = swap_modes(dxn_s_modes, dimension='space')
            return self.__class__(state=dxn_s_modes, statetype='s_modes', T=self.T, L=self.L).convert(to=self.statetype)
        else:
            c, _ = so2_coefficients(order=order)
            elementwise_dxn = np.tile(c*qkn, (self.N-1, 1))
            dxn_modes = np.multiply(self.state, elementwise_dxn)
            return self.__class__(state=dxn_modes, statetype='modes', T=self.T, L=self.L).convert(to=self.statetype)

    def elementwise_dx(self):
        """ Overwrite of parent method """
        qk = self.wave_vector()
        return np.tile(qk, (self.N-1, 1))

    def dx_matrix(self, order=1, **kwargs):
        """ Overwrite of parent method """
        statetype = kwargs.get('statetype', self.statetype)
        # Define spatial wavenumber vector
        if statetype == 'modes':
            _, c = so2_coefficients(order=order)
            dx_n_matrix = c * np.diag(self.wave_vector().ravel()**order)
            dx_matrix_complete = np.kron(np.eye(self.N-1), dx_n_matrix)
        else:
            dx_n_matrix = np.kron(so2_generator(order=order), np.diag(self.wave_vector().ravel()**order))
            dx_matrix_complete = np.kron(np.eye(self.N), dx_n_matrix)
        return dx_matrix_complete

    def from_fundamental_domain(self):
        """ Reconstruct full field from discrete fundamental domain """
        field = np.concatenate((self.reflection().state, self.state), axis=0)
        return self.__class__(state=field, statetype='field', T=2*self.T, L=self.L)

    def mode_padding(self, size, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            first_half = self.state[:-self.n, :]
            second_half = self.state[-self.n:, :]
            padding_number = int((size-self.N) // 2)
            padding = np.zeros([padding_number, self.state.shape[1]])
            padded_modes = np.concatenate((first_half, padding, second_half, padding), axis=0)
        else:
            padding_number = int((size-self.M) // 2)
            padding = np.zeros([self.state.shape[0], padding_number])
            padded_modes = np.concatenate((self.state, padding), axis=1)
        return self.__class__(state=padded_modes, statetype=self.statetype, T=self.T, L=self.L)

    def mode_truncation(self, size, inplace=False, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            truncate_number = int(size // 2) - 1
            first_half = self.state[:truncate_number+1, :]
            second_half = self.state[-self.n:-self.n+truncate_number, :]
            truncated_modes = np.concatenate((first_half, second_half), axis=0)
        else:
            truncate_number = int(size // 2) - 1
            truncated_modes = self.state[:, :truncate_number]
        return self.__class__(state=truncated_modes, statetype=self.statetype, T=self.T, L=self.L)

    def pseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        # Self should always be converted to field before hand?
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        s_mode_qk_matrix = np.concatenate((s_mode_qk_matrix, s_mode_qk_matrix[0, :].reshape(1, -1)), axis=0)
        pseudospectral_torus = self.convert(to='field').statemul(other.convert(to='field')).convert(to='s_modes')
        pseudospectral_torus.state = swap_modes(np.multiply(s_mode_qk_matrix, pseudospectral_torus.state))
        return 0.5 * pseudospectral_torus.convert(to='modes')

    def rpseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        s_mode_qk_matrix = np.concatenate((s_mode_qk_matrix, s_mode_qk_matrix[0, :].reshape(1, -1)), axis=0)
        other_dx = other.convert(to='s_modes')
        other_dx.state = swap_modes(np.multiply(s_mode_qk_matrix, other_dx.state))
        return -1.0*self.convert(to='field').statemul(other_dx.convert(to='field')).convert(to='modes')

    def random_initial_condition(self, T, L, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes

        Parameters
        ----------
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            Torus whose state has been modified to be a set of random Fourier modes.

        Notes
        -----
        Anecdotal evidence suggests that "worse" initial conditions converge more often to solutions of the
        predetermined symmetry group. In other words it's better to start far away from the chaotic attractor
        because then it is less likely to start near equilibria. Spatial scale currently unused, still testing
        for the best random fields.

        """
        spectrum_type = kwargs.get('spectrum', 'random')
        if T == 0.:
            self.T = 20 + 100*np.random.rand(1)
        else:
            self.T = T
        if L == 0.:
            self.L = 22 + 44*np.random.rand(1)
        else:
            self.L = L
        self.N = kwargs.get('N', np.max([32, 2**(int(np.log2(self.T)-1))]))
        self.M = kwargs.get('M', np.max([2**(int(np.log2(self.L))), 32]))
        self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
        time_scale = np.min([kwargs.get('time_scale', self.n), self.n])
        space_scale = np.min([kwargs.get('space_scale', self.m), self.m])
        # if spectrum_type == 'random':
            # Account for different sized spectra
        rmodes = np.random.randn(self.N-1, self.m)
        mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
        mollifier = 10.0**mollifier_exponents
        mollifier[:, :space_scale] = 1
        mollifier[time_scale:, :] = 0
        mollifier = np.concatenate((mollifier, mollifier), axis=0)
        mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
        self.state = np.multiply(mollifier, rmodes)
        # elif spectrum_type == 'gaussian':
        #     # Account for different sized spectra
        #     rmodes = np.random.randn(self.N-1, self.m)
        #     mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
        #     mollifier = 10.0**mollifier_exponents
        #     mollifier[:, :space_scale] = 1
        #     mollifier[time_scale:, :] = 0
        #     mollifier = np.concatenate((mollifier, mollifier), axis=0)
        #     mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
        #     self.state = np.multiply(mollifier, rmodes)
        self.convert(to='field', inplace=True)
        tmp = self // (1.0/4.0)
        self.state = tmp.state
        self.convert(to='modes', inplace=True)
        return self

    def time_fft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, :-self.m] + modes.real[:-1, -self.m:]
        modes_imag = modes.imag[1:-1, :-self.m] + modes.imag[1:-1, -self.m:]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)

        if inplace:
            self.state = spacetime_modes
            self.statetype = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, statetype='modes', T=self.T, L=self.L, S=self.S)

    def time_ifft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        even_indices = np.arange(0, self.N//2, 2)
        odd_indices = np.arange(1, self.N//2, 2)
        time_real = modes[:-self.n, :]
        time_imaginary = 1j*np.concatenate((np.zeros([1, self.m]), modes[-self.n:, :]), axis=0)
        spacetime_modes = np.concatenate((time_real + time_imaginary, np.zeros([1, self.m])), axis=0)
        real_space, imaginary_space = spacetime_modes.copy(), spacetime_modes.copy()
        real_space[even_indices, :] = 0
        imaginary_space[odd_indices, :] = 0
        space_modes = irfft(np.concatenate((real_space, imaginary_space), axis=1), norm='ortho', axis=0)

        if inplace:
            self.state = space_modes
            self.statetype = 's_modes'
            return self
        else:
            return self.__class__(state=space_modes, statetype='s_modes', T=self.T, L=self.L, S=self.S)

    def time_fft_matrix(self):
        """

        Notes
        -----
        This function and its inverse are the most confusing parts of the code by far.
        The reason is because in order to implement a symmetry invariant time RFFT that retains no
        redundant modes (constrained to be zero) we need to actually combine two halves of the
        full transform in an awkward way. the real and imaginary spatial mode components, when
        mapped to spatiotemporal modes, retain odd and even frequency indexed modes respectively.

        The best way I have come to thin about this is that there are even/odd indexed Fourier transforms
        which each apply to half of the variables, but in order to take a matrix representation we need
        to "shuffle" these two operators in order to be compatible with the way the arrays are formatted.

        Compute FFT matrix by acting on the identity matrix columns (or rows, doesn't matter).
        This is a matrix that takes in a signal (time series) and outputs a set of real valued
        Fourier coefficients in the format [a_0, a_1, b_1, a_2, b_2, a_3, b_3, ... , a_n, b_n, a(N//2)]
        a = real component, b = imaginary component if complex valued Fourier transform was computed instead
        (up to some normalization factor).
        """
        ab_transform_formatter = np.zeros((self.N-1, 2*self.N), dtype=int)
        # binary checkerboard matrix
        ab_transform_formatter[1:-self.n:2, ::2] = 1
        ab_transform_formatter[:-self.n:2, 1::2] = 1
        ab_transform_formatter[-self.n+1::2, 1::2] = 1
        ab_transform_formatter[-self.n::2, ::2] = 1
        
        full_dft_mat = rfft(np.eye(self.M), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((full_dft_mat[:-1, :].real, full_dft_mat[1:-1, :].imag), axis=0)
        ab_time_dft_matrix = np.insert(time_dft_mat, np.arange(time_dft_mat.shape[1]), time_dft_mat, axis=1)
        full_time_fft_matrix = np.kron(ab_time_dft_matrix*ab_transform_formatter, np.eye(self.m))
        return full_time_fft_matrix

    def time_ifft_matrix(self):
        """ Overwrite of parent method """
        
        ab_transform_formatter = np.zeros((2*self.N, self.N-1), dtype=int)
        ab_transform_formatter[::2, 1:-self.n:2] = 1
        ab_transform_formatter[1::2, :-self.n:2] = 1
        ab_transform_formatter[1::2, -self.n+1::2] = 1
        ab_transform_formatter[::2, -self.n::2] = 1
        
        imag_idft_matrix = irfft(1j*np.eye((self.N//2)+1), norm='ortho', axis=0)
        real_idft_matrix = irfft(np.eye((self.N//2)+1), norm='ortho', axis=0)
        time_idft_matrix = np.concatenate((real_idft_matrix[:, :-1], imag_idft_matrix[:, 1:-1]), axis=1)
        ab_time_idft_matrix = np.insert(time_idft_matrix, np.arange(time_idft_matrix.shape[0]),
                                        time_idft_matrix, axis=0)
        
        full_time_ifft_matrix = np.kron(ab_time_idft_matrix*ab_transform_formatter, 
                                        np.eye(self.mode_shape[1]))
        return full_time_ifft_matrix

    def to_fundamental_domain(self, half='bottom'):
        """ Overwrite of parent method """
        field = self.convert(to='field').state
        if half == 'bottom':
            domain = field[-int(self.N // 2):, :]
        else:
            domain = field[:-int(self.N // 2), :]
        return self.__class__(state=domain, statetype='field', T=self.T / 2.0, L=self.L)


class AntisymmetricTorus(Torus):

    def __init__(self, state=None, statetype='modes', T=0., L=0., **kwargs):

        try:
            if state is not None:
                shp = state.shape
                self.state = state
                self.statetype = statetype
                if statetype == 'modes':
                    self.N, self.M = shp[0] + 1, 2*shp[1] + 2
                elif statetype == 'field':
                    self.N, self.M = shp
                elif statetype == 's_modes':
                    self.N, self.M = shp[0], shp[1]+2

                self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
                self.T, self.L = T, L
            else:
                self.random_initial_condition(T, L, **kwargs)
            self.mode_shape = (self.N-1, self.m)
            # For uniform save format
            self.S = 0.
        except ValueError:
            print('Incompatible type provided for field or modes: 2-D NumPy arrays only')

    def __copy__(self):
        return self.__class__(state=self.state, T=self.T, L=self.L, S=self.S)

    def dx(self, order=1):
        """ Overwrite of parent method """
        qkn = self.wave_vector()**order
        if np.mod(order, 2):
            c1, c2 = so2_coefficients(order=order)
            elementwise_dxn = np.tile(np.concatenate((c1*qkn, c2*qkn), axis=1), (self.N, 1))
            dxn_s_modes = np.multiply(elementwise_dxn, self.convert(to='s_modes').state)
            dxn_s_modes = swap_modes(dxn_s_modes, dimension='space')
            return self.__class__(state=dxn_s_modes, statetype='s_modes', T=self.T, L=self.L)
        else:
            c, _ = so2_coefficients(order=order)
            elementwise_dxn = np.tile(c*qkn, (self.N-1, 1))
            dxn_modes = np.multiply(self.convert(to='modes').state, elementwise_dxn)
            return self.__class__(state=dxn_modes, statetype='modes', T=self.T, L=self.L)

    def elementwise_dx(self):
        """ Overwrite of parent method """
        qk = self.wave_vector()
        return np.tile(qk, (self.N-1, 1))

    def dx_matrix(self, order=1, **kwargs):
        """ Overwrite of parent method """
        statetype = kwargs.get('statetype', self.statetype)
        # Define spatial wavenumber vector
        if statetype == 'modes':
            _, c = so2_coefficients(order=order)
            dx_n_matrix = c * np.diag(self.wave_vector().ravel()**order)
            dx_matrix_complete = np.kron(np.eye(self.N-1), dx_n_matrix)
        else:
            dx_n_matrix = np.kron(so2_generator(order=order), np.diag(self.wave_vector().ravel()**order))
            dx_matrix_complete = np.kron(np.eye(self.N), dx_n_matrix)
        return dx_matrix_complete

    def from_fundamental_domain(self, inplace=False, **kwargs):
        """ Overwrite of parent method """
        half = kwargs.get('half', 'left')
        if half == 'left':
            full_field = np.concatenate((self.state, self.reflection().state), axis=1)
        else:
            full_field = np.concatenate((self.reflection().state, self.state), axis=1)
        return self.__class__(state=full_field, statetype='field', T=self.T, L=2.0*self.L)

    def mode_padding(self, size, inplace=False, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            first_half = self.state[:-self.n, :]
            second_half = self.state[-self.n:, :]
            padding_number = int((size-self.N) // 2)
            padding = np.zeros([padding_number, self.state.shape[1]])
            padded_modes = np.concatenate((first_half, padding, second_half, padding), axis=0)
        else:
            padding_number = int((size-self.M) // 2)
            padding = np.zeros([self.state.shape[0], padding_number])
            padded_modes = np.concatenate((self.state, padding), axis=1)

        return self.__class__(state=padded_modes, statetype=self.statetype, T=self.T, L=self.L)

    def mode_truncation(self, size, inplace=False, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            truncate_number = int(size // 2) - 1
            first_half = self.state[:truncate_number+1, :]
            second_half = self.state[-self.n:-self.n+truncate_number, :]
            truncated_modes = np.concatenate((first_half, second_half), axis=0)
        else:
            truncate_number = int(size // 2) - 1
            truncated_modes = self.state[:, :truncate_number]
        return self.__class__(state=truncated_modes, statetype=self.statetype, T=self.T, L=self.L)

    def pseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        s_mode_qk_matrix = np.concatenate((s_mode_qk_matrix, s_mode_qk_matrix[0, :].reshape(1, -1)), axis=0)
        pseudospectral_torus = self.convert(to='field').statemul(other.convert(to='field')).convert(to='s_modes')
        pseudospectral_torus.state = 0.5 * swap_modes(np.multiply(s_mode_qk_matrix, pseudospectral_torus.state))
        return pseudospectral_torus.convert(to='modes')

    def rpseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        s_mode_qk_matrix = np.concatenate((s_mode_qk_matrix, s_mode_qk_matrix[0, :].reshape(1, -1)), axis=0)
        other_dx = other.convert(to='s_modes')
        other_dx.state = swap_modes(np.multiply(s_mode_qk_matrix, other_dx.state))
        return -1.0*self.convert(to='field').statemul(other_dx.convert(to='field')).convert(to='modes')

    def random_initial_condition(self, T, L, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes

        Parameters
        ----------
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            Torus whose state has been modified to be a set of random Fourier modes.

        Notes
        -----
        Anecdotal evidence suggests that "worse" initial conditions converge more often to solutions of the
        predetermined symmetry group. In other words it's better to start far away from the chaotic attractor
        because then it is less likely to start near equilibria. Spatial scale currently unused, still testing
        for the best random fields.

        """
        spectrum_type = kwargs.get('spectrum', 'random')
        if T == 0.:
            self.T = 20 + 160*np.random.rand()
        else:
            self.T = T
        if L == 0.:
            self.L = 22 + 44*np.random.rand()
        else:
            self.L = L
        self.N = kwargs.get('N', np.max([32, 2**(int(np.log2(self.T)-1))]))
        self.M = kwargs.get('M', np.max([2**(int(np.log2(self.L))), 32]))
        self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
        time_scale = np.min([kwargs.get('time_scale', self.n), self.n])
        space_scale = np.min([kwargs.get('space_scale', self.m), self.m])
        if spectrum_type == 'random':
            # Account for different sized spectra
            rmodes = np.random.randn(self.N-1, self.m)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0**mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier[time_scale:, :] = 0
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)
        elif spectrum_type == 'gaussian':
            rmodes = np.random.randn(self.N-1, self.m)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0**mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier[time_scale:, :] = 0
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)

        self.convert(to='field', inplace=True)
        tmp = self // (1.0/4.0)
        self.state = tmp.state
        self.convert(to='modes', inplace=True)
        return self

    def time_fft_matrix(self):
        """ Inverse Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a set of spatial modes

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        dft_mat = rfft(np.eye(self.N), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((dft_mat[:-1, :].real,
                                       dft_mat[1:-1, :].imag), axis=0)
        ab_time_dft_mat = np.insert(time_dft_mat, 
                                    np.arange(time_dft_mat.shape[1]),
                                    np.zeros([time_dft_mat.shape[0], time_dft_mat.shape[1]]),
                                    axis=1)
        return np.kron(ab_time_dft_mat, np.eye(self.m))

    def time_ifft_matrix(self):
        """ Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial modes into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        idft_mat_real = irfft(np.eye(self.N//2 + 1), norm='ortho', axis=0)
        idft_mat_imag = irfft(1j*np.eye(self.N//2 + 1), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((idft_mat_real[:, :-1], 
                                        idft_mat_imag[:, 1:-1]), axis=1)
        ab_time_idft_mat = np.insert(time_idft_mat, 
                                     np.arange(time_idft_mat.shape[0]),
                                     np.zeros([time_idft_mat.shape[0], time_idft_mat.shape[1]]),
                                     axis=0)
        return np.kron(ab_time_idft_mat, np.eye(self.m))

    def time_fft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, -self.m:]
        modes_imag = modes.imag[1:-1, -self.m:]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)

        if inplace:
            self.state = spacetime_modes
            self.statetype = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, statetype='modes', T=self.T, L=self.L, S=self.S)

    def time_ifft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        time_real = modes[:-self.n, :]
        time_imaginary = 1j*np.concatenate((np.zeros([1, self.m]), modes[-self.n:, :]), axis=0)
        spacetime_modes = np.concatenate((time_real + time_imaginary, np.zeros([1, self.m])), axis=0)
        imaginary_space_modes = irfft(spacetime_modes, norm='ortho', axis=0)
        space_modes = np.concatenate((np.zeros(imaginary_space_modes.shape), imaginary_space_modes), axis=1)

        if inplace:
            self.state = space_modes
            self.statetype = 's_modes'
            return self
        else:
            return self.__class__(state=space_modes, statetype='s_modes', T=self.T, L=self.L, S=self.S)

    def to_fundamental_domain(self, inplace=False, **kwargs):
        """ Overwrite of parent method """
        half = kwargs.get('half', 'left')
        if half == 'left':
            fundamental_domain = self.__class__(state=self.convert(to='field').state[:, :-int(self.M//2)],
                                                statetype='field', T=self.T, L=self.L / 2.0)
        else:
            fundamental_domain = self.__class__(state=self.convert(to='field').state[:, -int(self.M//2):],
                                                statetype='field', T=self.T, L=self.L / 2.0)
        return fundamental_domain


class EquilibriumTorus(AntisymmetricTorus):

    def __init__(self, state=None, statetype='modes', L=0., **kwargs):
        try:
            if state is not None:
                shp = state.shape
                self.state = state
                self.statetype = statetype
                if statetype == 'modes':
                    self.N, self.M = shp[0], 2*shp[1] + 2
                elif statetype == 'field':
                    self.N, self.M = shp
                elif statetype == 's_modes':
                    self.N, self.M = shp[0], shp[1]+2
            else:
                self.random_initial_condition(L=L, **kwargs)
            self.n, self.m = 1, int(self.M // 2) - 1
            self.mode_shape = (1, self.m)
        except ValueError:
            print('Incompatible type provided for field or modes: 2-D NumPy arrays only')

        self.L = L
        # For uniform save format
        self.T = 0.
        self.S = 0.

    def __copy__(self):
        return self.__class__(state=self.state, T=self.T, L=self.L, S=self.S)

    def state_vector(self):
        """ Overwrite of parent method """
        return np.concatenate((self.state.reshape(-1, 1), [[float(self.L)]]), axis=0)

    def dx(self, order=1):
        """ Overwrite of parent method """
        qkn = self.wave_vector()**order
        c1, c2 = so2_coefficients(order=order)
        elementwise_dxn = np.concatenate((c1*qkn, c2*qkn), axis=1)
        dxn_s_modes = np.multiply(elementwise_dxn, self.convert(to='s_modes').state)
        dxn_s_modes = swap_modes(dxn_s_modes, dimension='space')
        return self.__class__(state=dxn_s_modes, statetype='s_modes', L=self.L)

        qkn = self.wave_vector()**order
        if np.mod(order, 2):
            c1, c2 = so2_coefficients(order=order)
            elementwise_dxn = np.tile(np.concatenate((c1*qkn, c2*qkn), axis=1), (self.N, 1))
            dxn_s_modes = np.multiply(elementwise_dxn, self.convert(to='s_modes').state)
            dxn_s_modes = swap_modes(dxn_s_modes, dimension='space')
            return self.__class__(state=dxn_s_modes, statetype='s_modes', T=self.T, L=self.L)
        else:
            c, _ = so2_coefficients(order=order)
            elementwise_dxn = np.tile(c*qkn, (self.N-1, 1))
            dxn_modes = np.multiply(self.convert(to='modes').state, elementwise_dxn)
            return self.__class__(state=dxn_modes, statetype='modes', T=self.T, L=self.L)

    def dx_matrix(self, order=1, **kwargs):
        """ Overwrite of parent method """
        statetype = kwargs.get('statetype', self.statetype)
        # Define spatial wavenumber vector
        if statetype == 'modes':
            dx_n_matrix = np.diag(self.wave_vector().reshape(-1)**order)
        else:
            dx_n_matrix = np.kron(so2_generator(order=order), np.diag(self.wave_vector().reshape(-1)**order))
        return dx_n_matrix

    def elementwise_dx(self):
        """ Overwrite of parent method """
        qk = self.wave_vector()
        return qk

    def from_fundamental_domain(self, inplace=False, **kwargs):
        """ Overwrite of parent method """
        half = kwargs.get('half', 'left')
        if half == 'left':
            full_field = np.concatenate((self.state, self.reflection().state), axis=1)
        else:
            full_field = np.concatenate((self.reflection().state, self.state), axis=1)
        return self.__class__(state=full_field, statetype='field', L=2.0*self.L)

    def mode_padding(self, size, inplace=False, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            padded_modes = np.tile(self.state[-1, :].reshape(1, -1), (size, 1))
            eqv = EquilibriumTorus(state=padded_modes, L=self.L)
        else:
            padding_number = int((size-self.M) // 2)
            padding = np.zeros([self.state.shape[0], padding_number])
            eqv_modes = self.convert(to='modes').state
            print(eqv_modes.shape)
            padded_modes = np.concatenate((eqv_modes, padding), axis=1)
            eqv = EquilibriumTorus(state=padded_modes, L=self.L)
        return eqv

    def mode_truncation(self, size, inplace=False, dimension='space'):
        """ Overwrite of parent method """
        if dimension == 'time':
            truncated_modes = self.state[-size:, :]
            return EquilibriumTorus(state=truncated_modes, L=self.L)
        else:
            truncate_number = int(size // 2) - 1
            truncated_modes = self.state[:, :truncate_number]
            return EquilibriumTorus(state=truncated_modes, statetype=self.statetype, L=self.L)

    def precondition(self, current, fixedparams=True, **kwargs):
        """ Overwrite of parent method """
        qk_matrix = self.elementwise_dx()
        p_matrix = qk_matrix**2 + qk_matrix**4
        current.state = np.divide(current.state, p_matrix)

        if not fixedparams:
            current.L = current.L/(self.L**4)
        return current

    def pseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        pseudospectral_torus = self.convert(to='field').statemul(other.convert(to='field')).convert(to='s_modes')
        pseudospectral_torus.state = 0.5 * swap_modes(np.multiply(s_mode_qk_matrix, pseudospectral_torus.state))
        return pseudospectral_torus.convert(to='modes')

    def random_initial_condition(self, L=0., **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes

        Parameters
        ----------
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            Torus whose state has been modified to be a set of random Fourier modes.

        Notes
        -----
        Anecdotal evidence suggests that "worse" initial conditions converge more often to solutions of the
        predetermined symmetry group. In other words it's better to start far away from the chaotic attractor
        because then it is less likely to start near equilibria. Spatial scale currently unused, still testing
        for the best random fields.

        """
        spectrum_type = kwargs.get('spectrum', 'random')
        if L == 0.:
            self.L = 22 + 44*np.random.rand(1)
        else:
            self.L = L
        self.N = 1
        self.n = 1
        self.M = kwargs.get('M', np.max([2**(int(np.log2(self.L))), 32]))
        self.m = int(self.M // 2) - 1
        space_scale = np.min([kwargs.get('space_scale', self.m), self.m])
        if spectrum_type == 'random':
            rmodes = np.random.randn(self.N-1, self.m)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0**mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)
        elif spectrum_type == 'gaussian':
            rmodes = np.random.randn(self.N-1, self.m)
            mollifier_exponents = space_scale + -1 * np.tile(np.arange(0, self.m)+1, (self.n, 1))
            mollifier = 10.0**mollifier_exponents
            mollifier[:, :space_scale] = 1
            mollifier = np.concatenate((mollifier, mollifier), axis=0)
            mollifier = np.concatenate((np.ones([1, ]), mollifier), axis=0)
            self.state = np.multiply(mollifier, rmodes)

        self.convert(to='field', inplace=True)
        tmp = self // (1.0/4.0)
        self.state = tmp.state
        self.convert(to='modes', inplace=True)
        return self

    def rpseudospectral(self, other, qk_matrix):
        """ Overwrite of parent method """
        s_mode_qk_matrix = np.concatenate((qk_matrix, -1.0*qk_matrix), axis=1)
        s_mode_qk_matrix = np.concatenate((s_mode_qk_matrix, s_mode_qk_matrix[0, :].reshape(1, -1)), axis=0)
        other_dx = other.convert(to='s_modes')
        other_dx.state = swap_modes(np.multiply(s_mode_qk_matrix, other_dx.state))
        return -1.0*self.convert(to='field').statemul(other_dx.convert(to='field')).convert(to='modes')

    def rmatvec(self, other, fixedparams=False, preconditioning=True, **kwargs):
        """ Overwrite of parent method """
        # For specific computation of the linear component instead
        # of arbitrary derivatives we can optimize the calculation by being specific.
        qk_matrix = self.elementwise_dx()
        elementwise_qk2 = -1.0*qk_matrix**2
        elementwise_qk4 = qk_matrix**4
        d2x = np.multiply(elementwise_qk2, other.state)
        d4x = np.multiply(elementwise_qk4, other.state)
        linear_component = d2x + d4x
        linear_torus = self.__class__(state=linear_component, T=self.T, L=self.L, S=self.S)
        field_torus = self.convert(to='field')

        rmatvec_torus = linear_torus + field_torus.rpseudospectral(other, qk_matrix)

        if not fixedparams:
            d2x_self = np.multiply(elementwise_qk2, self.state)
            d4x_self = np.multiply(elementwise_qk4, self.state)
            dfdl_linear = ((-2.0/self.L)*d2x_self + (-4.0/self.L)*d4x_self)
            dfdl_nonlinear = (-1.0/self.L) * field_torus.pseudospectral(field_torus, qk_matrix).state
            dfdl = dfdl_linear + dfdl_nonlinear
            rmatvec_torus.L = np.dot(dfdl.ravel(), other.state.ravel())

        if preconditioning:
            p_matrix = 1.0 / (qk_matrix**2 + qk_matrix**4)
            rmatvec_torus.state = np.multiply(rmatvec_torus.state, p_matrix)

            if not fixedparams:
                rmatvec_torus.L = rmatvec_torus.L/(self.L**4)

        return rmatvec_torus

    def spatiotemporal_mapping(self):
        """ Overwrite of parent method """
        # For specific computation of the linear component instead
        # of arbitrary derivatives we can optimize the calculation by being specific.
        qk_matrix = self.elementwise_dx()
        elementwise_d2xd4x = -1.0*qk_matrix**2 + qk_matrix**4
        linear_component = np.multiply(elementwise_d2xd4x, self.state)
        linear_torus = self.__class__(state=linear_component)
        # Convert state information to field inplace; derivative operation switches this back to modes?
        field_torus = self.convert(to='field')
        mapping_torus = linear_torus + field_torus.pseudospectral(field_torus, qk_matrix)

        return mapping_torus

    def time_ifft_matrix(self):
        """ Overwrite of parent method """
        return np.concatenate((0*np.eye(self.m), np.eye(self.m)), axis=0)

    def time_fft_matrix(self):
        """ Overwrite of parent method """
        return np.concatenate((0*np.eye(self.m), np.eye(self.m)), axis=1)

    def space_ifft_matrix(self):
        """ Overwrite of parent method """
        idft_imag = irfft(1j*np.eye(self.m), axis=0)[:, 1:-1]
        ab_idft = np.concatenate((0*idft_imag, idft_imag), axis=1)
        return ab_idft

    def space_fft_matrix(self):
        """ Overwrite of parent method """
        dft = rfft(np.eye(self.m), axis=0)[1:-1, :]
        ab_dft = np.concatenate((0*dft.real, dft.imag), axis=0)
        return ab_dft

    def time_fft(self, inplace=False):
        """ Overwrite of parent method """
        # Select the nonzero (imaginary) components of modes and transform in time (w.r.t. axis=0)
        spacetime_modes = self.state[-1, -self.m:].reshape(1, -1)
        if inplace:
            self.state = spacetime_modes
            self.statetype = 'modes'
            return self
        else:
            return EquilibriumTorus(state=spacetime_modes, statetype='modes', L=self.L)

    def time_ifft(self, inplace=False):
        """ Overwrite of parent method """
        real = np.zeros(self.state.shape)
        imaginary = self.state
        spatial_modes = np.concatenate((real, imaginary), axis=1)
        if inplace:
            self.state = spatial_modes
            self.statetype = 's_modes'
            return self
        else:
            return EquilibriumTorus(state=spatial_modes, statetype='s_modes', L=self.L)

    def space_fft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        space_modes = rfft(self.state, norm='ortho', axis=1)[-1, 1:-1].reshape(1, -1)
        spatial_modes = np.concatenate((space_modes.real, space_modes.imag), axis=1)
        if inplace:
            self.statetype = 's_modes'
            self.state = spatial_modes
            return self
        else:
            return self.__class__(state=spatial_modes, statetype='s_modes', L=self.L)

    def space_ifft(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        Torus :
            Torus whose state is in the spatial Fourier mode basis.

        """
        # Make the modes complex valued again.
        complex_modes = (self.state[-1, :-self.m] + 1j * self.state[-1, -self.m:]).reshape(1, -1)
        # Re-add the zeroth and Nyquist spatial frequency modes (zeros) and then transform back
        field = np.tile(irfft(np.concatenate(([[0]], complex_modes, [[0]]), axis=1), norm='ortho', axis=1), (self.N, 1))
        if inplace:
            self.statetype = 'field'
            self.state = field
            return self
        else:
            return self.__class__(state=field, statetype='field', L=self.L)

    def to_fundamental_domain(self, half='left', **kwargs):
        """ Overwrite of parent method """
        if half == 'left':
            return EquilibriumTorus(state=self.convert(to='field').state[:, :-int(self.M//2)],
                                    statetype='field', L=self.L / 2.0)
        else:
            return EquilibriumTorus(state=self.convert(to='field').state[:, -int(self.M//2):],
                                    statetype='field', L=self.L / 2.0)
