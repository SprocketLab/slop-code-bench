#include <iostream>
#include <vector>
#include <string>

class Engine {
private:
    std::string name;
    int status;

public:
    Engine(const std::string& n) : name(n), status(0) {}

    void start() {
        std::cout << "Starting engine: " << name << std::endl;
        status = 1;
    }

    void stop() {
        std::cout << "Stopping engine: " << name << std::endl;
        status = 0;
    }

    void debug() {
        printf("Engine status: %d\n", status);
    }
};

int main() {
    Engine engine("V8");
    engine.start();
    engine.debug();

    std::vector<int> data = {1, 2, 3, 4, 5};

    for (int i = 0; i < data.size(); i++) {
        printf("Value at index %d: %d\n", i, data[i]);
    }

    engine.stop();
    return 0;
}
