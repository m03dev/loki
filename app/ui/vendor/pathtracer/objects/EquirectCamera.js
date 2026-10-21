import { Camera } from '../../three/three.module.js';

export class EquirectCamera extends Camera {

	constructor() {

		super();

		this.isEquirectCamera = true;

	}

}
