/** 一次性 DOM 事件绑定，避免懒加载面板重复注册。 */

const boundKeys = new WeakMap();

export function bindOnce(element, key, type, handler, options) {
    if (!element) {
        return false;
    }
    let keys = boundKeys.get(element);
    if (!keys) {
        keys = new Set();
        boundKeys.set(element, keys);
    }
    if (keys.has(key)) {
        return false;
    }
    keys.add(key);
    element.addEventListener(type, handler, options);
    return true;
}
