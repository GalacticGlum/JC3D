/**
 * Author: Shon Verch
 * File Name: main.cpp
 * Project Name: JesusChristIn3D
 * Creation Date: 06/09/2019
 * Modified Date: 06/09/2019
 * Description: Entry point for the sandbox application.
 */

#include <Logger.h>
#include <Application.h>

class Sandbox : public Application
{
public:
	Sandbox()
	{
		
	}

	~Sandbox()
	{
		
	}
};

/**
 * Entry point for the sandbox application.
 */
int main(int argc, char** argv)
{
	Sandbox* sandbox = new Sandbox();
	sandbox->Run();
	delete sandbox;
}